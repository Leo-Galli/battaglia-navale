(function () {
  const cfg = window.BN_CONFIG || {};
  const STORAGE_LAST = 'bn_last_update_check';
  const STORAGE_SKIP = 'bn_skip_version';

  function parseParts(v) {
    return String(v || '')
      .replace(/^v/i, '')
      .split('.')
      .map((n) => parseInt(n, 10) || 0);
  }

  function isNewer(remoteTag, localVersion) {
    const a = parseParts(remoteTag);
    const b = parseParts(localVersion);
    for (let i = 0; i < Math.max(a.length, b.length); i++) {
      const x = a[i] || 0;
      const y = b[i] || 0;
      if (x > y) return true;
      if (x < y) return false;
    }
    return false;
  }

  function cap() {
    return window.Capacitor;
  }

  function plugins() {
    return cap()?.Plugins || {};
  }

  async function currentVersion() {
    try {
      const app = plugins().App;
      if (app?.getInfo) {
        const info = await app.getInfo();
        return info.version || '0.0.0';
      }
    } catch (_) {
      /* ignore */
    }
    return '0.0.0';
  }

  function shouldCheckNow() {
    const hours = cfg.updateCheckHours || 6;
    const last = parseInt(localStorage.getItem(STORAGE_LAST) || '0', 10);
    return Date.now() - last > hours * 3600 * 1000;
  }

  function setBannerVisible(show) {
    const el = document.getElementById('update-banner');
    if (el) el.hidden = !show;
  }

  async function fetchLatestRelease() {
    const url = cfg.githubReleasesLatest;
    if (!url) throw new Error('URL release non configurato');
    const res = await fetch(url, {
      headers: {
        Accept: 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
      },
    });
    if (!res.ok) throw new Error(`GitHub API ${res.status}`);
    return res.json();
  }

  function pickApkAsset(release) {
    const assets = release.assets || [];
    return assets.find((a) => /\.apk$/i.test(a.name));
  }

  async function ensureInstallPermission() {
    const install = plugins().InstallApk;
    if (!install?.canInstallPackages) return true;
    const res = await install.canInstallPackages();
    if (res.allowed) return true;
    if (install.openInstallPermissionSettings) {
      await install.openInstallPermissionSettings();
    }
    return false;
  }

  async function startDownload(apkUrl, releasePage) {
    const install = plugins().InstallApk;
    const status = document.getElementById('update-status');
    if (!install?.downloadAndInstall) {
      if (releasePage) window.open(releasePage, '_blank');
      return;
    }
    try {
      const ok = await ensureInstallPermission();
      if (!ok) {
        if (status) status.textContent = 'Abilita installazione da origini sconosciute per questo app.';
        return;
      }
      if (status) status.textContent = 'Download in corso…';
      await install.downloadAndInstall({ url: apkUrl });
      if (status) status.textContent = 'Apri il pacchetto quando il download è completato.';
    } catch (err) {
      const msg = String(err?.message || err);
      if (msg.includes('install_permission_required')) {
        await ensureInstallPermission();
        if (status) status.textContent = 'Concedi permesso installazione e riprova.';
        return;
      }
      if (releasePage) window.open(releasePage, '_blank');
      if (status) status.textContent = 'Download dal browser…';
    }
  }

  function bindUpdateUI(release, apk, localVersion) {
    const tag = release.tag_name || '';
    const title = document.getElementById('update-title');
    const body = document.getElementById('update-body');
    const status = document.getElementById('update-status');
    const btn = document.getElementById('btn-update');
    const skip = document.getElementById('btn-skip-update');

    if (title) title.textContent = `Aggiornamento ${tag}`;
    if (body) {
      const notes = (release.body || '').trim().slice(0, 280);
      body.textContent = notes || `Nuova versione rispetto a ${localVersion}.`;
    }
    if (status) status.textContent = apk ? `Pacchetto: ${apk.name}` : 'Asset APK non trovato nella release.';

    setBannerVisible(true);

    if (btn) {
      btn.onclick = () => {
        if (apk?.browser_download_url) startDownload(apk.browser_download_url, cfg.githubReleasePage);
        else if (cfg.githubReleasePage) window.open(cfg.githubReleasePage, '_blank');
      };
    }
    if (skip) {
      skip.onclick = () => {
        localStorage.setItem(STORAGE_SKIP, tag);
        setBannerVisible(false);
      };
    }
  }

  async function checkForUpdates(force) {
    const banner = document.getElementById('update-banner');
    if (!banner) return;
    if (!force && !shouldCheckNow()) return;

    localStorage.setItem(STORAGE_LAST, String(Date.now()));

    try {
      const localVersion = await currentVersion();
      const verLabel = document.getElementById('app-version');
      if (verLabel) verLabel.textContent = `v${localVersion}`;

      const release = await fetchLatestRelease();
      const tag = release.tag_name || '';
      if (localStorage.getItem(STORAGE_SKIP) === tag) return;
      if (!isNewer(tag, localVersion)) return;

      const apk = pickApkAsset(release);
      bindUpdateUI(release, apk, localVersion);
    } catch (err) {
      const status = document.getElementById('update-status');
      if (status) status.textContent = '';
      setBannerVisible(false);
    }
  }

  window.BNUpdate = { checkForUpdates };

  document.addEventListener('DOMContentLoaded', () => {
    checkForUpdates(false);
    const manual = document.getElementById('btn-check-update');
    if (manual) manual.addEventListener('click', () => checkForUpdates(true));
  });
})();
