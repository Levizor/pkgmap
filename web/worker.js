// Pure JavaScript Web Worker for pkgmap using official SQLite3 WASM (OPFS) and fzstd

const SQLITE_WASM_DIR = "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@3.46.1-build1/sqlite-wasm/jswasm/";

importScripts("https://cdn.jsdelivr.net/npm/fzstd@0.1.1/umd/index.js");
importScripts(SQLITE_WASM_DIR + "sqlite3.js");

// Tell SQLite WASM to locate sqlite3.wasm on CDN
if (self.sqlite3InitModuleState) {
  self.sqlite3InitModuleState.sqlite3Dir = SQLITE_WASM_DIR;
}

const DB_FILENAME = "pkgmap.db.zst";
const OPFS_DB_NAME = "/pkgmap.db";
const LEGACY_CACHE_NAME = "pkgmap-db-v3";

let db = null;
let sqlite3 = null;
let poolUtil = null;
let storageBackend = "unknown";

function queryRows(sql, params = []) {
  if (!db) return [];
  return db.exec({
    sql,
    bind: params,
    rowMode: "object",
    returnValue: "resultRows"
  });
}

async function streamDownloadToSAHPool(pool) {
  postMessage({ type: "status", message: "Connecting to database download...", downloading: true });
  let resp = await fetch(DB_FILENAME);
  if (!resp.ok) {
    resp = await fetch("https://github.com/Levizor/pkgmap/releases/latest/download/pkgmap.db.zst");
    if (!resp.ok) throw new Error(`Failed to download database: HTTP ${resp.status}`);
  }

  const totalBytes = parseInt(resp.headers.get("content-length") || "38781482", 10);
  const reader = resp.body.getReader();

  const chunkQueue = [];
  let notifyQueue = null;
  let streamDone = false;
  let streamError = null;

  const decompressor = new fzstd.Decompress((decompressedChunk, isLast) => {
    chunkQueue.push(decompressedChunk);
    if (notifyQueue) {
      const notify = notifyQueue;
      notifyQueue = null;
      notify();
    }
  });

  async function pumpNetwork() {
    try {
      let received = 0;
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          decompressor.push(new Uint8Array(0), true);
          break;
        }
        received += value.length;
        postMessage({
          type: "progress",
          percent: Math.min(100, Math.round((received / totalBytes) * 100)),
          receivedMb: (received / (1024 * 1024)).toFixed(1),
          totalMb: (totalBytes / (1024 * 1024)).toFixed(1)
        });
        decompressor.push(value, false);
        while (chunkQueue.length > 16) {
          await new Promise(r => setTimeout(r, 5));
        }
      }
    } catch (err) {
      streamError = err;
    } finally {
      streamDone = true;
      if (notifyQueue) {
        const notify = notifyQueue;
        notifyQueue = null;
        notify();
      }
    }
  }

  pumpNetwork();

  async function nextChunk() {
    while (chunkQueue.length === 0) {
      if (streamDone) {
        if (streamError) throw streamError;
        return undefined;
      }
      await new Promise(r => { notifyQueue = r; });
    }
    return chunkQueue.shift();
  }

  postMessage({ type: "status", message: "Streaming & decompressing database to persistent storage (OPFS)...", downloading: true });
  await pool.importDb(OPFS_DB_NAME, nextChunk);
}

async function downloadAndDecompressBuffer() {
  postMessage({ type: "status", message: "Downloading database (~37 MB compressed)...", downloading: true });
  let resp = await fetch(DB_FILENAME);
  if (!resp.ok) {
    resp = await fetch("https://github.com/Levizor/pkgmap/releases/latest/download/pkgmap.db.zst");
    if (!resp.ok) throw new Error(`Failed to download database: HTTP ${resp.status}`);
  }

  const totalBytes = parseInt(resp.headers.get("content-length") || "38781482", 10);
  const reader = resp.body.getReader();
  let received = 0;
  const chunks = [];

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    chunks.push(value);
    received += value.length;
    postMessage({
      type: "progress",
      percent: Math.min(100, Math.round((received / totalBytes) * 100)),
      receivedMb: (received / (1024 * 1024)).toFixed(1),
      totalMb: (totalBytes / (1024 * 1024)).toFixed(1)
    });
  }

  let compressed = new Uint8Array(received);
  let offset = 0;
  for (const chunk of chunks) {
    compressed.set(chunk, offset);
    offset += chunk.length;
  }
  chunks.length = 0;

  postMessage({ type: "status", message: "Decompressing database with fzstd..." });
  const decompressed = fzstd.decompress(compressed);
  compressed = null;
  if (decompressed.length > 20) {
    decompressed[18] = 1;
    decompressed[19] = 1;
  }
  return decompressed;
}

async function init() {
  try {
    postMessage({ type: "status", message: "Initializing SQLite WebAssembly..." });
    sqlite3 = await self.sqlite3InitModule();

    let opened = false;
    let dbBytes = null;

    // 1. Primary: SAHPool OPFS (fast, persistent, no COOP/COEP headers required)
    if (typeof sqlite3.installOpfsSAHPoolVfs === "function") {
      try {
        postMessage({ type: "status", message: "Connecting to persistent storage (OPFS)..." });
        poolUtil = await sqlite3.installOpfsSAHPoolVfs({ name: "opfs-sahpool" });
        const fileNames = poolUtil.getFileNames();

        // Clean up any legacy unslashed entry
        if (fileNames.includes("pkgmap.db")) {
          try { poolUtil.unlink("pkgmap.db"); } catch (_) {}
        }

        if (fileNames.includes(OPFS_DB_NAME)) {
          postMessage({ type: "status", message: "Opening database from persistent storage (OPFS)..." });
          try {
            db = new poolUtil.OpfsSAHPoolDb(OPFS_DB_NAME);
            db.selectValue("SELECT count(*) FROM repositories;");
            db.selectValue("SELECT count(*) FROM projects;");
            opened = true;
            storageBackend = "opfs-sahpool";
          } catch (e) {
            console.warn("Outdated or invalid SAHPool DB, unlinking:", e);
            if (db) { try { db.close(); } catch (_) {} db = null; }
            try { poolUtil.unlink(OPFS_DB_NAME); } catch (_) {}
          }
        }

        if (!opened) {
          await streamDownloadToSAHPool(poolUtil);
          postMessage({ type: "status", message: "Opening database from persistent storage (OPFS)..." });
          db = new poolUtil.OpfsSAHPoolDb(OPFS_DB_NAME);
          db.selectValue("SELECT count(*) FROM repositories;");
          opened = true;
          storageBackend = "opfs-sahpool";
        }
      } catch (sahErr) {
        console.warn("SAHPool OPFS failed, trying standard OPFS / in-memory:", sahErr);
        if (db) { try { db.close(); } catch (_) {} db = null; }
        poolUtil = null;
      }
    }

    // 2. Secondary fallback: Standard OPFS
    if (!opened && sqlite3.opfs && sqlite3.oo1?.OpfsDb) {
      try {
        const exists = await sqlite3.opfs.entryExists(OPFS_DB_NAME);
        if (exists) {
          postMessage({ type: "status", message: "Opening database from persistent storage (OPFS)..." });
          try {
            db = new sqlite3.oo1.OpfsDb(OPFS_DB_NAME);
            db.selectValue("SELECT count(*) FROM repositories;");
            db.selectValue("SELECT count(*) FROM projects;");
            opened = true;
            storageBackend = "opfs-standard";
          } catch (existingErr) {
            console.warn("Existing OPFS database invalid, removing:", existingErr);
            if (db) { try { db.close(); } catch (_) {} db = null; }
            await sqlite3.opfs.unlink(OPFS_DB_NAME).catch(() => {});
          }
        }

        if (!opened) {
          dbBytes = await downloadAndDecompressBuffer();
          postMessage({ type: "status", message: "Writing database to persistent storage (OPFS)..." });
          await sqlite3.oo1.OpfsDb.importDb(OPFS_DB_NAME, dbBytes);
          db = new sqlite3.oo1.OpfsDb(OPFS_DB_NAME);
          db.selectValue("SELECT count(*) FROM repositories;");
          opened = true;
          storageBackend = "opfs-standard";
          dbBytes = null;
        }
      } catch (opfsErr) {
        console.warn("Standard OPFS failed, falling back to in-memory:", opfsErr);
        if (db) { try { db.close(); } catch (_) {} db = null; }
        await sqlite3.opfs?.unlink?.(OPFS_DB_NAME).catch(() => {});
      }
    }

    // 3. Final fallback: in-memory
    if (!opened) {
      postMessage({ type: "status", message: "Loading database in-memory (OPFS not available)..." });
      if (!dbBytes) dbBytes = await downloadAndDecompressBuffer();
      const p = sqlite3.wasm.allocFromTypedArray(dbBytes);
      db = new sqlite3.oo1.DB();
      const rc = sqlite3.capi.sqlite3_deserialize(
        db.pointer, 'main', p, dbBytes.byteLength, dbBytes.byteLength,
        sqlite3.capi.SQLITE_DESERIALIZE_FREEONCLOSE
      );
      db.checkRc(rc);
      storageBackend = "in-memory";
      dbBytes = null;
    }

    db.exec("PRAGMA cache_size = 2000;");

    const allRepos = queryRows("SELECT id, name, family, package_count FROM repositories ORDER BY package_count DESC;");
    postMessage({
      type: "ready",
      repoCount: allRepos.length,
      allRepositories: allRepos,
      storageBackend
    });

  } catch (err) {
    postMessage({ type: "error", message: err.message || String(err) });
  }
}

function handleSuggest(queryId, q) {
  if (!db || !q?.trim()) return postMessage({ type: "suggest_result", id: queryId, suggestions: [] });
  const term = q.trim().toLowerCase();
  try {
    const upper = term.slice(0, -1) + String.fromCharCode(term.charCodeAt(term.length - 1) + 1);
    const effnames = queryRows("SELECT name FROM projects WHERE name >= ? AND name < ? LIMIT 8;", [term, upper]).map(r => r.name);

    if (!effnames.includes(term) && term.length >= 2) {
      const pkgRow = queryRows("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name = ? LIMIT 1;", [term])[0];
      if (pkgRow && !effnames.includes(pkgRow.name)) effnames.unshift(pkgRow.name);
    }

    const limited = effnames.slice(0, 8);
    if (!limited.length) return postMessage({ type: "suggest_result", id: queryId, query: term, suggestions: [] });

    const counts = Object.fromEntries(
      queryRows(`SELECT pr.name, count(*) as c FROM projects pr JOIN packages p ON pr.id = p.project_id WHERE pr.name IN (${limited.map(() => "?").join(",")}) GROUP BY pr.name;`, limited).map(r => [r.name, r.c])
    );
    const suggestions = limited.map(name => ({ effname: name, distro_count: counts[name] || 1 }));
    suggestions.sort((a, b) => (a.effname === term ? -1 : b.effname === term ? 1 : b.distro_count - a.distro_count));

    postMessage({ type: "suggest_result", id: queryId, query: term, suggestions });
  } catch (err) {
    postMessage({ type: "suggest_result", id: queryId, query: term, suggestions: [] });
  }
}

function resolveCanonicalEffname(term) {
  if (!db || !term) return null;
  const lower = term.trim().toLowerCase();
  const qProj = (sql, p) => queryRows(sql, p)[0]?.name;
  const qPkg = (sql, p) => queryRows(sql, p)[0]?.name;
  if (lower.length >= 2) {
    const upper = lower.slice(0, -1) + String.fromCharCode(lower.charCodeAt(lower.length - 1) + 1);
    return qProj("SELECT name FROM projects WHERE name = ? LIMIT 1;", [lower])
      || qPkg("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name = ? LIMIT 1;", [lower])
      || qProj("SELECT name FROM projects WHERE name >= ? AND name < ? LIMIT 1;", [lower, upper])
      || qPkg("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name LIKE ? || '%' LIMIT 1;", [lower]);
  }
  return qProj("SELECT name FROM projects WHERE name = ? LIMIT 1;", [lower])
    || qPkg("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name = ? LIMIT 1;", [lower]);
}

function resolveRepos(repoSlug) {
  if (!db || !repoSlug) return [];
  const slug = repoSlug.toLowerCase().trim();
  if (slug === "arch+aur" || slug === "arch_aur") {
    return queryRows("SELECT id, name, family FROM repositories WHERE name IN ('arch', 'aur');").sort((a, b) => (a.name === "arch" ? -1 : 1));
  }
  const row = queryRows("SELECT id, name, family FROM repositories WHERE name = ? LIMIT 1;", [slug])[0];
  if (row) return [row];
  const alias = queryRows("SELECT target_repo FROM repository_aliases WHERE alias = ? LIMIT 1;", [slug])[0];
  return alias ? queryRows("SELECT id, name, family FROM repositories WHERE name = ? LIMIT 1;", [alias.target_repo]) : [];
}

function handleMatrix(queryId, name) {
  if (!db || !name?.trim()) return postMessage({ type: "matrix_result", id: queryId, error: "Empty query" });
  const term = name.trim().toLowerCase();
  try {
    const effname = resolveCanonicalEffname(term);
    if (!effname) return postMessage({ type: "matrix_result", id: queryId, found: false, query: term });

    const allPackages = queryRows(`
      SELECT r.name as repo_name, r.family as repo_family, p.package_name, p.version, r.package_count
      FROM projects pr
      JOIN packages p ON pr.id = p.project_id
      JOIN repositories r ON p.repo_id = r.id
      WHERE pr.name = ?
      ORDER BY r.package_count DESC;
    `, [effname]);

    postMessage({
      type: "matrix_result", id: queryId, found: true, query: term,
      effname, totalDistros: allPackages.length, allPackages
    });
  } catch (err) {
    postMessage({ type: "matrix_result", id: queryId, error: err.message || String(err), found: false, query: term });
  }
}

function sortBatchMatches(matches, lower) {
  const rank = (m) => [
    m.dst_repo_name === "aur" ? 1 : 0,
    m.package_name.toLowerCase() === lower ? 0 : 1,
    (m.package_name.endsWith("-git") || m.package_name.endsWith("-bin")) ? 1 : 0,
    (/[./]/.test(m.package_name)) ? 1 : 0,
    m.package_name.length
  ];
  matches.sort((a, b) => {
    const ra = rank(a), rb = rank(b);
    for (let i = 0; i < ra.length; i++) {
      if (ra[i] !== rb[i]) return ra[i] - rb[i];
    }
    return 0;
  });
}

function handleBatchResolve(queryId, packages, fromRepo, toRepo) {
  if (!db || !packages || !toRepo) return postMessage({ type: "batch_result", id: queryId, results: [] });

  try {
    const isGeneric = !fromRepo || ["any", "all"].includes(fromRepo.toLowerCase());
    const dstRepos = resolveRepos(toRepo);
    if (!dstRepos.length) return postMessage({ type: "batch_result", id: queryId, error: "Invalid target repository selection", results: [] });
    const dstIn = dstRepos.map(r => r.id).join(",");

    let srcRepos = [], srcIn = "";
    if (!isGeneric) {
      srcRepos = resolveRepos(fromRepo);
      if (!srcRepos.length) return postMessage({ type: "batch_result", id: queryId, error: "Invalid source repository selection", results: [] });
      srcIn = srcRepos.map(r => r.id).join(",");
    }

    const uniqueInputs = [...new Set(packages.map(p => p.trim()).filter(Boolean))];
    const queryDstPkg = (val) => queryRows(`SELECT p.package_name, p.version, pr.name as effname, r.name as dst_repo_name FROM packages p JOIN projects pr ON p.project_id = pr.id JOIN repositories r ON p.repo_id = r.id WHERE p.repo_id IN (${dstIn}) AND p.package_name = ?;`, [val]);
    const queryDstProj = (val) => queryRows(`SELECT p.package_name, p.version, pr.name as effname, r.name as dst_repo_name FROM projects pr JOIN packages p ON pr.id = p.project_id JOIN repositories r ON p.repo_id = r.id WHERE p.repo_id IN (${dstIn}) AND pr.name = ?;`, [val]);
    const queryStrictPkg = (val) => queryRows(`SELECT dst.package_name, dst.version, pr.name as effname, r.name as dst_repo_name FROM packages src JOIN projects pr ON src.project_id = pr.id JOIN packages dst ON src.project_id = dst.project_id JOIN repositories r ON dst.repo_id = r.id WHERE src.repo_id IN (${srcIn}) AND src.package_name = ? AND dst.repo_id IN (${dstIn});`, [val]);
    const queryStrictProj = (val) => queryRows(`SELECT dst.package_name, dst.version, pr.name as effname, r.name as dst_repo_name FROM projects pr JOIN packages src ON pr.id = src.project_id JOIN packages dst ON src.project_id = dst.project_id JOIN repositories r ON dst.repo_id = r.id WHERE src.repo_id IN (${srcIn}) AND pr.name = ? AND dst.repo_id IN (${dstIn});`, [val]);

    const results = uniqueInputs.map(inputPkg => {
      const lower = inputPkg.toLowerCase();
      let matches = !isGeneric ? queryStrictPkg(inputPkg) : queryDstPkg(inputPkg);
      if (!matches.length) matches = !isGeneric ? queryStrictProj(inputPkg) : queryDstProj(inputPkg);
      if (isGeneric && !matches.length) {
        const eff = resolveCanonicalEffname(inputPkg) || queryRows("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name = ? LIMIT 1;", [inputPkg])[0]?.name;
        if (eff) matches = queryDstProj(eff);
      }

      if (matches.length > 0) {
        sortBatchMatches(matches, lower);
        const best = matches[0];
        return { input: inputPkg, resolved: true, targetName: best.package_name, targetVersion: best.version, repoSource: best.dst_repo_name, effname: best.effname, matchCount: matches.length };
      }
      let unresEffname = null;
      if (!isGeneric) {
        const srcMatch = queryRows(`SELECT pr.name FROM packages src JOIN projects pr ON src.project_id = pr.id WHERE src.repo_id IN (${srcIn}) AND (src.package_name = ? OR pr.name = ?) LIMIT 1;`, [inputPkg, inputPkg])[0];
        if (srcMatch) unresEffname = srcMatch.name;
      } else {
        unresEffname = resolveCanonicalEffname(inputPkg) || queryRows("SELECT pr.name FROM packages p JOIN projects pr ON p.project_id = pr.id WHERE p.package_name = ? LIMIT 1;", [inputPkg])[0]?.name;
      }
      const notInSource = !isGeneric && !unresEffname;
      return { input: inputPkg, resolved: false, targetName: null, targetVersion: null, effname: unresEffname, reason: notInSource ? "not_in_source" : "not_in_target" };
    });

    postMessage({
      type: "batch_result",
      id: queryId,
      fromRepo: isGeneric ? "any" : (fromRepo === "arch+aur" ? "arch+aur" : srcRepos[0].name),
      toRepo: toRepo === "arch+aur" ? "arch+aur" : dstRepos[0].name,
      dstFamily: dstRepos[0].family,
      results
    });
  } catch (err) {
    postMessage({ type: "batch_result", id: queryId, error: err.message, results: [] });
  }
}

self.onmessage = (e) => {
  const { type, id, query, name, packages, fromRepo, toRepo } = e.data;
  if (type === "suggest") handleSuggest(id, query);
  else if (type === "matrix") handleMatrix(id, name);
  else if (type === "batch") handleBatchResolve(id, packages, fromRepo, toRepo);
  else if (type === "clear_cache") {
    (async () => {
      try {
        if (db) {
          try { db.close(); } catch (_) {}
          db = null;
        }
        if (poolUtil) {
          try { poolUtil.unlink(OPFS_DB_NAME); } catch (_) {}
          try { poolUtil.unlink("pkgmap.db"); } catch (_) {}
        }
        if (sqlite3?.opfs) {
          await sqlite3.opfs.unlink(OPFS_DB_NAME).catch(() => {});
        }
        try {
          const root = await navigator.storage?.getDirectory?.();
          if (root) {
            await root.removeEntry("pkgmap.db").catch(() => {});
            await root.removeEntry(".opfs-sahpool", { recursive: true }).catch(() => {});
          }
        } catch (_) {}
        try {
          await caches.delete(LEGACY_CACHE_NAME);
        } catch (_) {}
        postMessage({ type: "cache_cleared" });
      } catch (err) {
        postMessage({ type: "error", message: "Failed to clear database: " + err.message });
      }
    })();
  }
};

init();
