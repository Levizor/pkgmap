// Pure JavaScript Web Worker for pkgmap using sql.js (SQLite WASM) and fzstd

importScripts("https://cdn.jsdelivr.net/npm/fzstd@0.1.1/umd/index.js");
importScripts("https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.12.0/sql-wasm.js");

const DB_FILENAME = "pkgmap.db.zst";
const CACHE_NAME = "pkgmap-db-v3";
const CACHE_KEY = "pkgmap.db";

let db = null;

function queryRows(sql, params = []) {
  if (!db) return [];
  const stmt = db.prepare(sql);
  if (params.length) stmt.bind(params);
  const rows = [];
  while (stmt.step()) rows.push(stmt.getAsObject());
  stmt.free();
  return rows;
}

async function init() {
  try {
    postMessage({ type: "status", message: "Initializing SQLite WebAssembly..." });
    const SQL = await initSqlJs({ locateFile: (f) => `https://cdnjs.cloudflare.com/ajax/libs/sql.js/1.12.0/${f}` });

    let dbBytes = null, cache = null;
    try {
      cache = await caches.open(CACHE_NAME);
      const cached = await cache.match(CACHE_KEY);
      if (cached) {
        postMessage({ type: "status", message: "Loading database from browser storage..." });
        dbBytes = new Uint8Array(await cached.arrayBuffer());
      }
    } catch (e) {
      console.warn("Cache API check failed:", e);
    }

    if (!dbBytes) {
      postMessage({ type: "status", message: "Downloading database (~45 MB compressed)...", downloading: true });
      let resp = await fetch(DB_FILENAME);
      if (!resp.ok) {
        resp = await fetch("https://github.com/Levizor/pkgmap/releases/latest/download/pkgmap.db.zst");
        if (!resp.ok) throw new Error(`Failed to download database: HTTP ${resp.status}`);
      }

      const totalBytes = parseInt(resp.headers.get("content-length") || "46300000", 10);
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
      dbBytes = fzstd.decompress(compressed);
      compressed = null;
      if (cache) cache.put(CACHE_KEY, new Response(dbBytes)).catch(e => console.warn("Cache write failed:", e));
    }

    postMessage({ type: "status", message: "Opening SQLite database..." });
    db = new SQL.Database(dbBytes);
    dbBytes = null;

    const allRepos = queryRows("SELECT id, name, family, package_count FROM repositories ORDER BY package_count DESC;");
    postMessage({ type: "ready", repoCount: allRepos.length, allRepositories: allRepos });

  } catch (err) {
    postMessage({ type: "error", message: err.message || String(err) });
  }
}

function handleSuggest(queryId, q) {
  if (!db || !q?.trim()) return postMessage({ type: "suggest_result", id: queryId, suggestions: [] });
  const term = q.trim().toLowerCase();
  try {
    const upper = term.slice(0, -1) + String.fromCharCode(term.charCodeAt(term.length - 1) + 1);
    const effnames = queryRows("SELECT DISTINCT effname FROM packages WHERE effname >= ? AND effname < ? LIMIT 8;", [term, upper]).map(r => r.effname);

    if (!effnames.includes(term) && term.length >= 2) {
      const pkgRow = queryRows("SELECT effname FROM packages WHERE package_name = ? LIMIT 1;", [term])[0];
      if (pkgRow && !effnames.includes(pkgRow.effname)) effnames.unshift(pkgRow.effname);
    }

    const limited = effnames.slice(0, 8);
    if (!limited.length) return postMessage({ type: "suggest_result", id: queryId, query: term, suggestions: [] });

    const counts = Object.fromEntries(
      queryRows(`SELECT effname, count(*) as c FROM packages WHERE effname IN (${limited.map(() => "?").join(",")}) GROUP BY effname;`, limited).map(r => [r.effname, r.c])
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
  const q = (sql, p) => queryRows(sql, p)[0]?.effname;
  if (lower.length >= 2) {
    const upper = lower.slice(0, -1) + String.fromCharCode(lower.charCodeAt(lower.length - 1) + 1);
    return q("SELECT effname FROM packages WHERE effname = ? LIMIT 1;", [lower])
      || q("SELECT effname FROM packages WHERE package_name = ? LIMIT 1;", [lower])
      || q("SELECT effname FROM packages WHERE effname >= ? AND effname < ? LIMIT 1;", [lower, upper])
      || q("SELECT effname FROM packages WHERE package_name LIKE ? || '%' LIMIT 1;", [lower]);
  }
  return q("SELECT effname FROM packages WHERE effname = ? LIMIT 1;", [lower])
    || q("SELECT effname FROM packages WHERE package_name = ? LIMIT 1;", [lower]);
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
      FROM packages p JOIN repositories r ON p.repo_id = r.id
      WHERE p.effname = ?
      ORDER BY r.package_count DESC;
    `, [effname]);

    const latestVersion = allPackages.find(p => p.version)?.version || null;
    postMessage({
      type: "matrix_result", id: queryId, found: true, query: term,
      effname, totalDistros: allPackages.length, latestVersion, allPackages
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
    const queryDst = (field, val) => queryRows(`SELECT p.package_name, p.version, r.name as dst_repo_name FROM packages p JOIN repositories r ON p.repo_id = r.id WHERE p.repo_id IN (${dstIn}) AND p.${field} = ?;`, [val]);
    const queryStrict = (field, val) => queryRows(`SELECT dst.package_name, dst.version, r.name as dst_repo_name FROM packages src JOIN packages dst ON src.effname = dst.effname JOIN repositories r ON dst.repo_id = r.id WHERE src.repo_id IN (${srcIn}) AND src.${field} = ? AND dst.repo_id IN (${dstIn});`, [val]);

    const results = uniqueInputs.map(inputPkg => {
      const lower = inputPkg.toLowerCase();
      let matches = !isGeneric ? queryStrict("package_name", inputPkg) : queryDst("package_name", inputPkg);
      if (!matches.length) matches = !isGeneric ? queryStrict("effname", inputPkg) : queryDst("effname", inputPkg);
      if (isGeneric && !matches.length) {
        const eff = resolveCanonicalEffname(inputPkg) || queryRows("SELECT effname FROM packages WHERE package_name = ? LIMIT 1;", [inputPkg])[0]?.effname;
        if (eff) matches = queryDst("effname", eff);
      }

      if (matches.length > 0) {
        sortBatchMatches(matches, lower);
        const best = matches[0];
        return { input: inputPkg, resolved: true, targetName: best.package_name, targetVersion: best.version, repoSource: best.dst_repo_name, matchCount: matches.length };
      }
      const notInSource = !isGeneric && queryRows(`SELECT 1 FROM packages WHERE repo_id IN (${srcIn}) AND (package_name = ? OR effname = ?) LIMIT 1;`, [inputPkg, inputPkg]).length === 0;
      return { input: inputPkg, resolved: false, targetName: null, targetVersion: null, reason: notInSource ? "not_in_source" : "not_in_target" };
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
    caches.delete(CACHE_NAME).then(() => postMessage({ type: "cache_cleared" }))
      .catch(err => postMessage({ type: "error", message: "Failed to clear cache: " + err.message }));
  }
};

init();
