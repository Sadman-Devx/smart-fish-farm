/**
 * AquaSmart PWA Client Script
 * ─────────────────────────────────────────────────────────────────
 * Handles:
 *   1. Service Worker registration
 *   2. Install prompt (Add to Home Screen)
 *   3. Online/Offline status banner
 *   4. Update notification
 */

(function () {
  'use strict';

  // ── 1. Register Service Worker ──────────────────────────────────
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker
        .register('/static/pwa/sw.js', { scope: '/' })
        .then(function (reg) {
          console.log('[PWA] Service Worker registered. Scope:', reg.scope);

          // Check for updates every 60 seconds
          setInterval(function () { reg.update(); }, 60000);

          // New version available
          reg.addEventListener('updatefound', function () {
            var newWorker = reg.installing;
            newWorker.addEventListener('statechange', function () {
              if (newWorker.state === 'installed' && navigator.serviceWorker.controller) {
                showUpdateBanner();
              }
            });
          });
        })
        .catch(function (err) {
          console.warn('[PWA] Service Worker registration failed:', err);
        });

      // Reload when new SW takes over
      navigator.serviceWorker.addEventListener('controllerchange', function () {
        window.location.reload();
      });
    });
  }

  // ── 2. Install Prompt (Add to Home Screen) ──────────────────────
  var deferredPrompt = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    deferredPrompt = e;
    showInstallBanner();
  });

  window.addEventListener('appinstalled', function () {
    deferredPrompt = null;
    hideInstallBanner();
    console.log('[PWA] App installed successfully');
  });

  function showInstallBanner() {
    // Don't show if already installed (standalone mode)
    if (window.matchMedia('(display-mode: standalone)').matches) return;
    if (localStorage.getItem('pwa-install-dismissed')) return;

    var banner = document.createElement('div');
    banner.id  = 'pwa-install-banner';
    banner.innerHTML = `
      <div style="
        position:fixed;bottom:20px;left:50%;transform:translateX(-50%);
        background:#111e35;border:1px solid rgba(0,229,180,.3);
        border-radius:14px;padding:14px 18px;
        display:flex;align-items:center;gap:14px;
        box-shadow:0 8px 32px rgba(0,0,0,.5);z-index:9999;
        max-width:400px;width:calc(100% - 32px);
        animation:slideUp .3s ease-out;
      ">
        <style>
          @keyframes slideUp {
            from { opacity:0; transform:translateX(-50%) translateY(20px); }
            to   { opacity:1; transform:translateX(-50%) translateY(0); }
          }
        </style>
        <div style="font-size:28px;flex-shrink:0">🐟</div>
        <div style="flex:1;min-width:0">
          <div style="font-family:'Syne',sans-serif;font-weight:800;
                      font-size:14px;color:#e8f4ff;margin-bottom:3px">
            Install AquaSmart
          </div>
          <div style="font-size:12px;color:#7a95b8">
            Add to home screen for quick access
          </div>
        </div>
        <button id="pwa-install-btn" style="
          background:#00e5b4;color:#0a1628;
          font-family:'Syne',sans-serif;font-weight:800;
          font-size:12px;border:none;border-radius:8px;
          padding:8px 14px;cursor:pointer;white-space:nowrap;
          flex-shrink:0;
        ">Install</button>
        <button id="pwa-dismiss-btn" style="
          background:none;border:none;color:#7a95b8;
          cursor:pointer;font-size:18px;padding:4px;
          flex-shrink:0;line-height:1;
        ">×</button>
      </div>
    `;
    document.body.appendChild(banner);

    document.getElementById('pwa-install-btn').addEventListener('click', function () {
      if (!deferredPrompt) return;
      deferredPrompt.prompt();
      deferredPrompt.userChoice.then(function (result) {
        if (result.outcome === 'accepted') {
          console.log('[PWA] User accepted install');
        }
        deferredPrompt = null;
        hideInstallBanner();
      });
    });

    document.getElementById('pwa-dismiss-btn').addEventListener('click', function () {
      localStorage.setItem('pwa-install-dismissed', '1');
      hideInstallBanner();
    });
  }

  function hideInstallBanner() {
    var banner = document.getElementById('pwa-install-banner');
    if (banner) banner.remove();
  }

  // ── 3. Online / Offline status banner ───────────────────────────
  var offlineBanner = null;

  function showOfflineBanner() {
    if (offlineBanner) return;
    offlineBanner = document.createElement('div');
    offlineBanner.id = 'pwa-offline-banner';
    offlineBanner.innerHTML = `
      <div style="
        position:fixed;top:0;left:0;right:0;z-index:10000;
        background:rgba(239,68,68,.12);
        border-bottom:1px solid rgba(239,68,68,.3);
        padding:8px 16px;
        display:flex;align-items:center;justify-content:center;
        gap:8px;font-size:13px;color:#ef4444;
        font-family:'Space Grotesk',sans-serif;
      ">
        <span style="
          width:7px;height:7px;border-radius:50%;
          background:#ef4444;flex-shrink:0;
          animation:blink2 1.5s ease-in-out infinite;
        "></span>
        <style>
          @keyframes blink2 {
            0%,100%{opacity:1} 50%{opacity:.3}
          }
        </style>
        <strong>You're offline</strong> — Showing cached data. Changes will sync when reconnected.
      </div>
    `;
    document.body.prepend(offlineBanner);
  }

  function hideOfflineBanner() {
    if (offlineBanner) {
      offlineBanner.remove();
      offlineBanner = null;
    }
    // Show "back online" toast
    showToast('✅ Back online — data synced', 'success');
  }

  window.addEventListener('offline', showOfflineBanner);
  window.addEventListener('online',  hideOfflineBanner);
  if (!navigator.onLine) showOfflineBanner();

  // ── 4. Update available banner ───────────────────────────────────
  function showUpdateBanner() {
    showToast(
      '🔄 New version available — <button onclick="location.reload()" ' +
      'style="background:none;border:none;color:#00e5b4;cursor:pointer;' +
      'font-weight:700;text-decoration:underline;padding:0;font-size:inherit">Refresh</button>',
      'info',
      0   // stay until dismissed
    );
  }

  // ── Toast helper ─────────────────────────────────────────────────
  function showToast(message, type, duration) {
    if (duration === undefined) duration = 4000;

    var colors = {
      success: { bg: 'rgba(16,185,129,.12)', border: 'rgba(16,185,129,.3)', color: '#10b981' },
      info:    { bg: 'rgba(0,184,255,.12)',  border: 'rgba(0,184,255,.3)',  color: '#00b8ff' },
      warn:    { bg: 'rgba(245,158,11,.12)', border: 'rgba(245,158,11,.3)', color: '#f59e0b' },
      danger:  { bg: 'rgba(239,68,68,.12)',  border: 'rgba(239,68,68,.3)',  color: '#ef4444' },
    };
    var c = colors[type] || colors.info;

    var toast = document.createElement('div');
    toast.style.cssText = `
      position:fixed;bottom:80px;left:50%;transform:translateX(-50%);
      background:${c.bg};border:1px solid ${c.border};
      color:${c.color};border-radius:10px;
      padding:10px 18px;font-size:13px;
      font-family:'Space Grotesk',sans-serif;
      z-index:9998;white-space:nowrap;
      box-shadow:0 4px 16px rgba(0,0,0,.3);
      animation:slideUp2 .3s ease-out;
    `;
    toast.innerHTML = `
      <style>@keyframes slideUp2{from{opacity:0;transform:translateX(-50%) translateY(10px)}to{opacity:1;transform:translateX(-50%) translateY(0)}}</style>
      ${message}
    `;
    document.body.appendChild(toast);

    if (duration > 0) {
      setTimeout(function () {
        toast.style.opacity = '0';
        toast.style.transition = 'opacity .3s';
        setTimeout(function () { toast.remove(); }, 300);
      }, duration);
    }
  }

  // ── 5. Standalone mode detection ────────────────────────────────
  if (window.matchMedia('(display-mode: standalone)').matches) {
    console.log('[PWA] Running in standalone mode (installed app)');
    document.documentElement.setAttribute('data-pwa', 'standalone');
  }

})();