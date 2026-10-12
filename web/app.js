// Minimalist, fast cross-distribution package lookup
const POPULAR_DISTROS = [
  { id: "arch", label: "Arch (+ AUR)", batchLabel: "Arch Linux (+ AUR)", batchValue: "arch+aur", preferred: "arch", prefixes: ["arch", "aur"] },
  { id: "debian", label: "Debian", preferred: "debian_unstable", prefixes: ["debian"] },
  { id: "ubuntu", label: "Ubuntu", preferred: "ubuntu", prefixes: ["ubuntu"] },
  { id: "fedora", label: "Fedora", preferred: "fedora", prefixes: ["fedora"] },
  { id: "nixpkgs", label: "Nixpkgs", preferred: "nix_unstable", prefixes: ["nix"] },
  { id: "alpine", label: "Alpine", preferred: "alpine_edge", prefixes: ["alpine"] },
  { id: "void", label: "Void", preferred: "void_x86_64", prefixes: ["void"] },
  { id: "opensuse", label: "openSUSE", preferred: "opensuse_tumbleweed", prefixes: ["opensuse"] },
  { id: "gentoo", label: "Gentoo", preferred: "gentoo", prefixes: ["gentoo"] },
];

const DB_VARIANT_STORAGE_KEY = "pkgmap_db_variant";
let currentDbVariant = "core";
try {
  if (localStorage.getItem(DB_VARIANT_STORAGE_KEY) === "full") {
    currentDbVariant = "full";
  }
} catch (_) {}

let worker = null, suggestId = 0, matrixId = 0, batchId = 0, uiInitialized = false;
let suggestDebounce = null, searchDebounce = null, currentSuggestions = [];
let activeDistroIds = new Set(POPULAR_DISTROS.map(d => d.id)), showAllRepos = false, allFilterQuery = "", currentPackageData = null;
let allRepositoriesList = [], lastBatchResult = null;

const $ = (id) => document.getElementById(id);
const elStatusContainer = $("status-container"), elStatusMessage = $("status-message"),
  elProgressBar = $("progress-bar"), elProgressFill = $("progress-fill"),
  elAppContainer = $("app-container"), elSearchInput = $("search-input"),
  elSuggestionsContainer = $("suggestions-container"), elSuggestionsList = $("suggestions-list"),
  elResultsContainer = $("results-container"), elResultsSummary = $("results-summary"),
  elResultsEffname = $("results-effname"), elResultsRepologyLink = $("results-repology-link"),
  elResultsTargets = $("results-targets"), elResultsEmpty = $("results-empty"),
  elResultsTableWrap = $("results-table-wrap"), elResultsTable = $("results-table"),
  elClearCacheBtn = $("clear-cache-btn"), elDistroPills = $("distro-pills"),
  elBtnToggleAllRepos = $("btn-toggle-all-repos"), elTabSingle = $("tab-single"),
  elTabBatch = $("tab-batch"), elViewSingle = $("view-single"), elViewBatch = $("view-batch"),
  elBatchSrcRepo = $("batch-src-repo"), elBatchDstRepo = $("batch-dst-repo"),
  elBatchInput = $("batch-input"), elBatchResolveBtn = $("batch-resolve-btn"),
  elBatchStatusMsg = $("batch-status-msg"), elBatchResultsContainer = $("batch-results-container"),
  elBatchStats = $("batch-stats"), elBatchStatsCount = $("batch-stats-count"),
  elBatchStatsPct = $("batch-stats-pct"), elBatchStatsFrom = $("batch-stats-from"),
  elBatchStatsTo = $("batch-stats-to"), elBatchResultsTable = $("batch-results-table"),
  elBatchCopyList = $("batch-copy-list"), elDbVariantSwitcher = $("db-variant-switcher");

// DOM Templates
const tmplSingleRow = $("tmpl-single-row"), tmplBatchRow = $("tmpl-batch-row"),
  tmplEmptyRow = $("tmpl-empty-row"), tmplSuggestionChip = $("tmpl-suggestion-chip"),
  tmplDistroPill = $("tmpl-distro-pill");

function shouldAutoFocus() {
  return !(window.matchMedia("(pointer: coarse)").matches || window.innerWidth < 768);
}

function safeFocus(el) {
  if (shouldAutoFocus()) {
    el?.focus();
  }
}

function updateVariantButtons(variant) {
  if (!elDbVariantSwitcher) return;
  elDbVariantSwitcher.querySelectorAll("button[data-variant]").forEach(btn => {
    btn.classList.toggle("active", btn.dataset.variant === variant);
  });
}

function syncPopularDistroPreferredRepos() {
  for (const d of POPULAR_DISTROS) {
    if (d.id === "arch") continue;
    const exact = allRepositoriesList.find(r => r.name === d.preferred);
    if (exact) {
      d.resolvedRepo = exact.name;
      continue;
    }
    const prefixMatch = allRepositoriesList.find(r =>
      d.prefixes.some(pre => r.name === pre || r.name.startsWith(pre + "_"))
    );
    d.resolvedRepo = prefixMatch ? prefixMatch.name : d.preferred;
  }
}

function initVariantSwitcher() {
  updateVariantButtons(currentDbVariant);
  if (!elDbVariantSwitcher) return;
  elDbVariantSwitcher.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-variant]");
    if (!btn || !worker) return;
    const targetVariant = btn.dataset.variant === "full" ? "full" : "core";
    if (targetVariant === currentDbVariant) return;

    currentDbVariant = targetVariant;
    try {
      localStorage.setItem(DB_VARIANT_STORAGE_KEY, currentDbVariant);
    } catch (_) {}
    updateVariantButtons(currentDbVariant);

    elAppContainer.classList.add("hidden");
    elStatusContainer.classList.remove("hidden");
    elProgressBar.classList.add("hidden");
    elProgressFill.style.width = "0%";
    elStatusMessage.textContent = `Switching to ${currentDbVariant === "core" ? "Core" : "Full"} database...`;
    worker.postMessage({ type: "switch_variant", variant: currentDbVariant });
  });
}

function initWorker() {
  initVariantSwitcher();

  if (window.location.protocol === "file:") {
    $("file-protocol-warning")?.classList.remove("hidden");
    $("status-spinner")?.classList.add("hidden");
    elStatusMessage?.classList.add("hidden");
    $("status-hint")?.classList.add("hidden");
    return;
  }

  const sqliteCdnDir = "https://cdn.jsdelivr.net/npm/@sqlite.org/sqlite-wasm@3.46.1-build1/sqlite-wasm/jswasm";
  worker = new Worker(`worker.js?sqlite3.dir=${encodeURIComponent(sqliteCdnDir)}&variant=${encodeURIComponent(currentDbVariant)}`);

  worker.onerror = (err) => {
    elStatusMessage.textContent = `Worker Error: ${err.message || "Failed to load Web Worker"}`;
  };

  worker.onmessage = (e) => {
    const d = e.data;
    if (d.type === "status") {
      elStatusMessage.textContent = d.message;
      if (d.downloading) elProgressBar.classList.remove("hidden");
    } else if (d.type === "progress") {
      if (d.percent !== null && d.percent !== undefined) {
        elProgressFill.style.width = `${d.percent}%`;
        elStatusMessage.textContent = `Downloading database: ${d.percent}% (${d.receivedMb} / ${d.totalMb} MB)`;
      } else {
        elProgressFill.style.width = "100%";
        elStatusMessage.textContent = `Downloading database: ${d.receivedMb} MB`;
      }
    } else if (d.type === "ready") {
      if (d.variant) {
        currentDbVariant = d.variant;
        updateVariantButtons(currentDbVariant);
      }
      elStatusContainer.classList.add("hidden");
      elAppContainer.classList.remove("hidden");
      if (d.storageBackend) {
        const variantLabel = currentDbVariant === "core" ? "Core" : "Full";
        console.log("pkgmap: database ready, variant:", currentDbVariant, "storage backend:", d.storageBackend);
        const elBadge = $("storage-badge");
        if (elBadge) {
          if (d.storageBackend.startsWith("opfs")) {
            elBadge.textContent = `SQLite WASM (OPFS · ${variantLabel})`;
            elBadge.title = `Persistent disk-backed storage via ${d.storageBackend} (${d.repoCount} repositories)`;
          } else {
            elBadge.textContent = `SQLite WASM (Memory · ${variantLabel})`;
            elBadge.title = `In-memory database (${d.repoCount} repositories)`;
          }
        }
      }
      allRepositoriesList = d.allRepositories || [];
      syncPopularDistroPreferredRepos();
      renderDistroPills();
      if (!uiInitialized) {
        initDistroFilterBar();
        initBatchView();
        uiInitialized = true;
      } else {
        populateBatchRepoDropdowns();
      }
      const activeQuery = elSearchInput.value.trim() || "bat";
      elSearchInput.value = activeQuery;
      safeFocus(elSearchInput);
      triggerMatrix(activeQuery);
      triggerSuggest();
      if (!elViewBatch.classList.contains("hidden") && elBatchInput.value.trim()) {
        triggerBatchResolve();
      }
    } else if (d.type === "suggest_result" && d.id === suggestId) {
      renderSuggestions(d.suggestions);
    } else if (d.type === "matrix_result" && d.id === matrixId) {
      currentPackageData = d;
      renderResults();
      renderDistroPills();
      if (currentSuggestions.length > 0) renderSuggestions(currentSuggestions);
    } else if (d.type === "batch_result" && d.id === batchId) {
      renderBatchResults(d);
    } else if (d.type === "error") {
      elStatusMessage.textContent = `Error: ${d.message}`;
    } else if (d.type === "cache_cleared") {
      try { localStorage.removeItem(DB_VARIANT_STORAGE_KEY); } catch (_) {}
      alert("Local database cache cleared. Reloading page...");
      window.location.reload();
    }
  };
}

function triggerSuggest() {
  const query = elSearchInput.value.trim();
  if (!query) return hideSuggestions();
  worker.postMessage({ type: "suggest", id: ++suggestId, query });
}

function triggerMatrix(name) {
  const query = (name || elSearchInput.value).trim();
  if (query) worker.postMessage({ type: "matrix", id: ++matrixId, name: query });
}

function renderSuggestions(suggestions) {
  currentSuggestions = suggestions || [];
  if (!elSuggestionsContainer || !elSuggestionsList) return;
  if (!currentSuggestions.length || (currentSuggestions.length === 1 && currentPackageData && currentSuggestions[0].effname === currentPackageData.effname)) {
    return hideSuggestions();
  }
  const activeEffname = currentPackageData?.effname;
  elSuggestionsList.replaceChildren();
  const frag = document.createDocumentFragment();
  currentSuggestions.forEach((item, idx) => {
    const btn = tmplSuggestionChip.content.cloneNode(true).firstElementChild;
    btn.dataset.index = idx;
    const active = activeEffname && item.effname === activeEffname;
    if (active) btn.classList.add("active");
    btn.querySelector(".chip-name").textContent = `${active ? "✓ " : ""}${item.effname}`;
    const cnt = btn.querySelector(".chip-count");
    cnt.textContent = `(${item.distro_count})`;
    if (active) cnt.className = "chip-count text-[10px] text-emerald-400/70 font-normal";
    frag.appendChild(btn);
  });
  elSuggestionsList.appendChild(frag);
  elSuggestionsContainer.classList.remove("hidden");
}

function hideSuggestions() {
  if (elSuggestionsContainer) elSuggestionsContainer.classList.add("hidden");
  if (elSuggestionsList) elSuggestionsList.replaceChildren();
  currentSuggestions = [];
}

const REPO_LABELS = {
  any: "Any / Upstream", "arch+aur": "Arch Linux (+ AUR)", arch: "Arch Linux (official)", aur: "Arch (AUR)",
  debian_12: "Debian 12", debian_11: "Debian 11", debian_13: "Debian 13", debian_unstable: "Debian Unstable",
  ubuntu_24_04: "Ubuntu 24.04", ubuntu_22_04: "Ubuntu 22.04", fedora_41: "Fedora 41", fedora_40: "Fedora 40",
  fedora_rawhide: "Fedora Rawhide", nix_unstable: "Nixpkgs", alpine_3_20: "Alpine 3.20", alpine_edge: "Alpine Edge",
  void_x86_64: "Void Linux", opensuse_tumbleweed: "openSUSE", freebsd: "FreeBSD", gentoo: "Gentoo",
  homebrew: "Homebrew", macports: "MacPorts", gnuguix: "GNU Guix", termux: "Termux", kali_rolling: "Kali Linux"
};
const formatRepoLabel = (r) => REPO_LABELS[r] || r.split("_").map(w => w[0].toUpperCase() + w.slice(1)).join(" ");

function copyToClipboard(text, btn) {
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "Copied!";
    btn.classList.add("text-emerald-400");
    setTimeout(() => {
      btn.textContent = "Copy";
      btn.classList.remove("text-emerald-400");
    }, 1500);
  });
}

function initDistroFilterBar() {
  if (!elBtnToggleAllRepos) return;
  elBtnToggleAllRepos.addEventListener("click", () => {
    showAllRepos = !showAllRepos;
    allFilterQuery = "";
    renderDistroPills();
    renderResults();
  });
  if (elDistroPills) {
    elDistroPills.addEventListener("click", (e) => {
      const btn = e.target.closest("button[data-distro]");
      if (!btn) return;
      const id = btn.dataset.distro;
      if (activeDistroIds.has(id)) {
        if (activeDistroIds.size > 1) activeDistroIds.delete(id);
      } else {
        activeDistroIds.add(id);
      }
      renderDistroPills();
      renderResults();
    });
  }
}

function renderDistroPills() {
  if (!elDistroPills) return;
  if (showAllRepos) {
    elBtnToggleAllRepos.textContent = "← Back to popular";
    let inp = $("all-filter-input");
    if (!inp) {
      elDistroPills.replaceChildren();
      const input = document.createElement("input");
      input.type = "text";
      input.id = "all-filter-input";
      input.placeholder = "Filter repos (e.g. aur, kali, guix)...";
      input.className = "repo-filter-input";
      input.value = allFilterQuery;
      input.addEventListener("input", (e) => {
        allFilterQuery = e.target.value.toLowerCase().trim();
        renderResults();
      });
      elDistroPills.appendChild(input);
      input.focus();
    } else if (document.activeElement !== inp) {
      inp.value = allFilterQuery;
    }
    return;
  }

  elBtnToggleAllRepos.textContent = currentPackageData ? `Show all (${currentPackageData.totalDistros})` : "Show all repos";
  elDistroPills.replaceChildren();
  const frag = document.createDocumentFragment();
  POPULAR_DISTROS.forEach(d => {
    const btn = tmplDistroPill.content.cloneNode(true).firstElementChild;
    btn.dataset.distro = d.id;
    const active = activeDistroIds.has(d.id);
    if (active) btn.classList.add("active");
    btn.textContent = `${active ? "✓ " : ""}${d.label}`;
    frag.appendChild(btn);
  });
  elDistroPills.appendChild(frag);
}

function renderResults() {
  if (!currentPackageData) return;
  elResultsContainer.classList.remove("hidden");

  if (!currentPackageData.found) {
    elResultsSummary.classList.add("hidden");
    elResultsTableWrap.classList.add("hidden");
    elResultsEmpty.textContent = `No package found for "${currentPackageData.query}"`;
    elResultsEmpty.classList.remove("hidden");
    return;
  }

  elResultsEmpty.classList.add("hidden");
  elResultsSummary.classList.remove("hidden");
  elResultsTableWrap.classList.remove("hidden");

  const { effname, totalDistros, allPackages } = currentPackageData;
  elResultsEffname.textContent = effname;
  if (elResultsRepologyLink) {
    elResultsRepologyLink.href = `https://repology.org/project/${encodeURIComponent(effname)}/information`;
    elResultsRepologyLink.title = `View ${effname} on Repology`;
  }
  elResultsTargets.textContent = `${totalDistros} repo targets`;

  let rows = [];
  if (!showAllRepos) {
    rows = POPULAR_DISTROS.filter(d => activeDistroIds.has(d.id)).map(d => {
      const prefRepo = d.resolvedRepo || d.preferred;
      const matches = (allPackages || []).filter(p => {
        const repo = p.repo_name.toLowerCase();
        return d.prefixes.some(pre => repo === pre || repo.startsWith(pre + "_"));
      });
      if (!matches.length) return { label: d.label, repoName: prefRepo, packaged: false };
      matches.sort((a, b) => {
        const aPref = a.repo_name === prefRepo, bPref = b.repo_name === prefRepo;
        if (aPref !== bPref) return bPref - aPref;
        const aAur = a.repo_name === "aur", bAur = b.repo_name === "aur";
        if (aAur !== bAur) return aAur - bAur;
        return b.package_count - a.package_count;
      });
      const best = matches[0];
      return {
        label: d.label, repoName: best.repo_name, packaged: true,
        packageName: best.package_name, version: best.version, isCombinedArch: d.id === "arch"
      };
    });
  } else {
    let filtered = allPackages || [];
    if (allFilterQuery) {
      filtered = filtered.filter(p => p.repo_name.toLowerCase().includes(allFilterQuery) || p.package_name.toLowerCase().includes(allFilterQuery) || p.repo_family.toLowerCase().includes(allFilterQuery));
    }
    rows = filtered.map(p => ({
      label: formatRepoLabel(p.repo_name), repoName: p.repo_name,
      packaged: true, packageName: p.package_name, version: p.version
    }));
  }

  elResultsTable.replaceChildren();
  if (!rows.length) {
    const emptyRow = tmplEmptyRow.content.cloneNode(true);
    emptyRow.querySelector(".empty-msg").textContent = "No matching repositories";
    elResultsTable.appendChild(emptyRow);
    return;
  }

  const frag = document.createDocumentFragment();
  for (const r of rows) {
    const tr = tmplSingleRow.content.cloneNode(true);
    tr.querySelector(".row-label").textContent = r.label;
    tr.querySelector(".row-repo").textContent = `(${r.repoName})`;
    if (r.packaged) {
      tr.querySelector(".row-pkg").textContent = r.packageName;
      const aur = tr.querySelector(".row-aur");
      if (r.isCombinedArch && r.repoName === "aur") {
        aur.classList.remove("hidden");
      } else {
        aur.remove();
      }
      tr.querySelector(".btn-copy").dataset.copy = r.packageName;
    } else {
      tr.querySelector(".row-packaged").classList.add("hidden");
      tr.querySelector(".row-unpackaged").classList.remove("hidden");
      tr.querySelector(".btn-copy").remove();
    }
    tr.querySelectorAll(".row-version").forEach(el => {
      el.textContent = r.version ? `v${r.version}` : "—";
    });
    frag.appendChild(tr);
  }
  elResultsTable.appendChild(frag);
}

// Input listeners
elSearchInput.addEventListener("input", () => {
  const query = elSearchInput.value.trim();
  clearTimeout(suggestDebounce);
  suggestDebounce = setTimeout(triggerSuggest, 70);
  clearTimeout(searchDebounce);
  if (query.length >= 2) {
    searchDebounce = setTimeout(() => triggerMatrix(query), 250);
  } else if (!query.length) {
    hideSuggestions();
    if (elResultsContainer) elResultsContainer.classList.add("hidden");
  }
});

elSearchInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    clearTimeout(searchDebounce);
    clearTimeout(suggestDebounce);
    triggerMatrix();
  } else if (e.key === "Escape") {
    hideSuggestions();
  }
});

elClearCacheBtn.addEventListener("click", () => {
  if (confirm("Clear local database cache and re-download on next load?")) {
    worker.postMessage({ type: "clear_cache" });
  }
});

if (elSuggestionsList) {
  elSuggestionsList.addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-index]");
    if (!btn) return;
    const chosen = currentSuggestions[parseInt(btn.dataset.index, 10)]?.effname;
    if (chosen) {
      clearTimeout(searchDebounce);
      clearTimeout(suggestDebounce);
      elSearchInput.value = chosen;
      triggerMatrix(chosen);
    }
  });
}

function initBatchView() {
  if (!elTabSingle || !elTabBatch) return;
  elTabSingle.addEventListener("click", () => switchTab("single"));
  elTabBatch.addEventListener("click", () => switchTab("batch"));
  populateBatchRepoDropdowns();

  if (elBatchResolveBtn) elBatchResolveBtn.addEventListener("click", triggerBatchResolve);
  if (elBatchInput) {
    elBatchInput.addEventListener("keydown", (e) => {
      if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
        e.preventDefault();
        triggerBatchResolve();
      }
    });
  }

  if (elBatchCopyList) {
    elBatchCopyList.addEventListener("click", () => {
      if (!lastBatchResult) return;
      const names = (lastBatchResult.results || []).filter(r => r.resolved).map(r => r.targetName);
      if (!names.length) return;
      navigator.clipboard.writeText(names.join(" ")).then(() => {
        elBatchCopyList.textContent = "Copied package list!";
        elBatchCopyList.classList.add("text-emerald-400");
        setTimeout(() => {
          elBatchCopyList.textContent = "Copy package list";
          elBatchCopyList.classList.remove("text-emerald-400");
        }, 1500);
      });
    });
  }
}

function switchTab(mode) {
  const isSingle = mode === "single";
  elTabSingle.className = `mode-tab-btn ${isSingle ? "active" : ""}`;
  elTabBatch.className = `mode-tab-btn ${isSingle ? "" : "active"}`;
  elViewSingle.classList.toggle("hidden", !isSingle);
  elViewBatch.classList.toggle("hidden", isSingle);
  safeFocus(isSingle ? elSearchInput : elBatchInput);
}

function populateBatchRepoDropdowns() {
  if (!elBatchSrcRepo || !elBatchDstRepo) return;
  const prevSrc = elBatchSrcRepo.value;
  const prevDst = elBatchDstRepo.value;

  const createGroup = (label, repos, isPopular) => {
    const grp = document.createElement("optgroup");
    grp.label = label;
    for (const r of repos) {
      const opt = document.createElement("option");
      const pref = r.resolvedRepo || r.preferred;
      opt.value = isPopular ? (r.batchValue || pref) : r.name;
      opt.textContent = isPopular ? (r.batchLabel || `${r.label} (${pref})`) : `${formatRepoLabel(r.name)} (${r.name})`;
      grp.appendChild(opt);
    }
    return grp;
  };

  const popSet = new Set(POPULAR_DISTROS.map(d => d.resolvedRepo || d.preferred));
  const otherRepos = allRepositoriesList
    .filter(r => !popSet.has(r.name) || r.name === "arch" || r.name === "aur")
    .sort((a, b) => a.name.localeCompare(b.name));

  const anyOpt = document.createElement("option");
  anyOpt.value = "any";
  anyOpt.textContent = "Any / Upstream (Generic)";

  elBatchSrcRepo.replaceChildren(anyOpt, createGroup("Popular Distributions", POPULAR_DISTROS, true), createGroup("All Repositories", otherRepos, false));
  elBatchDstRepo.replaceChildren(createGroup("Popular Distributions", POPULAR_DISTROS, true), createGroup("All Repositories", otherRepos, false));

  const hasOption = (selectEl, val) => Array.from(selectEl.options).some(o => o.value === val);
  elBatchSrcRepo.value = (prevSrc && hasOption(elBatchSrcRepo, prevSrc)) ? prevSrc : "any";
  elBatchDstRepo.value = (prevDst && hasOption(elBatchDstRepo, prevDst)) ? prevDst : "arch+aur";
}

function triggerBatchResolve() {
  if (!elBatchInput || !worker) return;
  const pkgs = [...new Set(elBatchInput.value.split(/[\s,]+/).map(s => s.trim()).filter(Boolean))];
  if (!pkgs.length) {
    if (elBatchStatusMsg) {
      elBatchStatusMsg.textContent = "Please enter at least one package name.";
      elBatchStatusMsg.className = "text-amber-400";
    }
    return;
  }
  if (elBatchStatusMsg) {
    elBatchStatusMsg.textContent = `Resolving ${pkgs.length} package${pkgs.length === 1 ? "" : "s"}...`;
    elBatchStatusMsg.className = "text-zinc-400";
  }
  if (elBatchResolveBtn) elBatchResolveBtn.disabled = true;
  worker.postMessage({ type: "batch", id: ++batchId, packages: pkgs, fromRepo: elBatchSrcRepo.value, toRepo: elBatchDstRepo.value });
}

function renderBatchResults(data) {
  if (elBatchResolveBtn) elBatchResolveBtn.disabled = false;
  lastBatchResult = data;
  if (data.error) {
    if (elBatchStatusMsg) {
      elBatchStatusMsg.textContent = `Error: ${data.error}`;
      elBatchStatusMsg.className = "text-red-400";
    }
    if (elBatchResultsContainer) elBatchResultsContainer.classList.add("hidden");
    return;
  }

  const results = data.results || [];
  const resolvedCount = results.filter(r => r.resolved).length;
  const totalCount = results.length;
  const percent = totalCount > 0 ? Math.round((resolvedCount / totalCount) * 100) : 0;
  if (elBatchStatusMsg) elBatchStatusMsg.textContent = "";

  if (elBatchStatsCount) {
    elBatchStatsCount.textContent = `${resolvedCount} / ${totalCount}`;
    elBatchStatsPct.textContent = `resolved (${percent}%)`;
    elBatchStatsFrom.textContent = formatRepoLabel(data.fromRepo);
    elBatchStatsTo.textContent = formatRepoLabel(data.toRepo);
  }

  elBatchResultsTable.replaceChildren();
  if (!results.length) {
    const emptyRow = tmplEmptyRow.content.cloneNode(true);
    emptyRow.querySelector(".empty-msg").textContent = "No packages entered";
    elBatchResultsTable.appendChild(emptyRow);
  } else {
    const frag = document.createDocumentFragment();
    for (const r of results) {
      const tr = tmplBatchRow.content.cloneNode(true);
      tr.querySelector(".row-input").textContent = r.input;
      const projName = r.effname;
      const repoAction = tr.querySelector(".btn-repology-action");
      if (repoAction) {
        if (projName) {
          repoAction.href = `https://repology.org/project/${encodeURIComponent(projName)}/information`;
          repoAction.title = `View project "${projName}" on Repology`;
          repoAction.classList.remove("hidden");
        } else {
          repoAction.remove();
        }
      }

      if (r.resolved) {
        tr.querySelector(".row-target").textContent = r.targetName;
        const aur = tr.querySelector(".row-aur");
        if (r.repoSource === "aur" && data.toRepo === "arch+aur") {
          aur.classList.remove("hidden");
        } else {
          aur.remove();
        }
        if (r.targetVersion) {
          tr.querySelector(".row-version").textContent = `v${r.targetVersion}`;
        }
        tr.querySelector(".btn-copy").dataset.copy = r.targetName;
      } else {
        tr.querySelector(".row-resolved").classList.add("hidden");
        const unres = tr.querySelector(".row-unresolved");
        unres.textContent = r.reason === "not_in_source" ? `Not found in ${formatRepoLabel(data.fromRepo)}` : "Not found in target";
        unres.classList.remove("hidden");
        tr.querySelector(".btn-copy").remove();
      }
      frag.appendChild(tr);
    }
    elBatchResultsTable.appendChild(frag);
  }

  if (elBatchResultsContainer) elBatchResultsContainer.classList.remove("hidden");
}

document.addEventListener("click", (e) => {
  const btn = e.target.closest(".btn-copy[data-copy]");
  if (btn) copyToClipboard(btn.dataset.copy, btn);
});

initWorker();
