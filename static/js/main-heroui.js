(function () {
    'use strict';
    if (!document.body.classList.contains('heroui-main')) return;

    if (window.navigator.standalone === true ||
        window.matchMedia('(display-mode: standalone)').matches) {
        document.documentElement.classList.add('heroui-pwa');
    }

    document.addEventListener('mousemove', function (e) {
        document.body.style.setProperty('--mx', e.clientX + 'px');
        document.body.style.setProperty('--my', e.clientY + 'px');
    });

    function initCardSpotlight() {
        var card = document.querySelector('.movie-hero-card');
        if (!card) return;

        card.addEventListener('mousemove', function (e) {
            var rect = card.getBoundingClientRect();
            card.style.setProperty('--card-mx', (e.clientX - rect.left) + 'px');
            card.style.setProperty('--card-my', (e.clientY - rect.top) + 'px');
        });

        card.addEventListener('mouseleave', function () {
            card.style.setProperty('--card-mx', '-9999px');
            card.style.setProperty('--card-my', '-9999px');
        });
    }

    function initPosterTilt() {
        var posterCol = document.querySelector('.poster-col');
        var poster = posterCol && posterCol.querySelector('.movie_poster');
        if (!poster) return;

        poster.addEventListener('mousemove', function (e) {
            var rect = poster.getBoundingClientRect();
            var cx = rect.left + rect.width / 2;
            var cy = rect.top + rect.height / 2;
            var dx = (e.clientX - cx) / (rect.width / 2);
            var dy = (e.clientY - cy) / (rect.height / 2);
            var rotX = -dy * 8;
            var rotY = dx * 8;
            poster.style.transform =
                'perspective(600px) rotateX(' + rotX + 'deg) rotateY(' + rotY + 'deg) scale(1.03)';
        });

        poster.addEventListener('mouseleave', function () {
            poster.style.transform = '';
        });
    }

    function initMovieLoadTransition() {
        var card = document.querySelector('.movie-hero-card');
        var poster = document.getElementById('poster_img');
        var bgDiv = document.getElementById('img_background');
        if (!card || !poster) return;

        var pendingPoster = false;
        var pendingBg = false;
        var safetyTimer = null;

        function checkReveal() {
            if (!card.classList.contains('heroui-refreshing')) return;
            if (pendingPoster || pendingBg) return;
            card.classList.remove('heroui-refreshing');
        }

        document.addEventListener('click', function (e) {
            if (!e.target.closest) return;
            if (e.target.closest('#btn_next_movie') || e.target.closest('#btn_get_movie')) {
                card.classList.add('heroui-refreshing');
                pendingPoster = true;
                pendingBg = true;
                clearTimeout(safetyTimer);
                safetyTimer = setTimeout(function () {
                    pendingPoster = false;
                    pendingBg = false;
                    card.classList.remove('heroui-refreshing');
                }, 5000);
            }
        }, true);

        new MutationObserver(function () {
            if (!card.classList.contains('heroui-refreshing')) return;
            var src = poster.getAttribute('src');
            if (!src) { pendingPoster = false; checkReveal(); return; }
            var img = new Image();
            img.onload = img.onerror = function () { pendingPoster = false; checkReveal(); };
            img.src = src;
        }).observe(poster, { attributes: true, attributeFilter: ['src'] });

        if (bgDiv) {
            new MutationObserver(function () {
                if (!card.classList.contains('heroui-refreshing')) return;
                var match = (bgDiv.style.backgroundImage || '').match(/url\(["']?([^"')]+)["']?\)/);
                if (!match) { pendingBg = false; checkReveal(); return; }
                var img = new Image();
                img.onload = img.onerror = function () { pendingBg = false; checkReveal(); };
                img.src = match[1];
            }).observe(bgDiv, { attributes: true, attributeFilter: ['style'] });
        } else {
            pendingBg = false;
        }
    }

    function initMovieContentObserver() {
        var content = document.getElementById('movieContent');
        if (!content) return;

        var cardReady = false;

        function onVisibilityChange() {
            if (!content.classList.contains('hidden')) {
                document.body.classList.add('has-movie');
                if (!cardReady) {
                    cardReady = true;
                    initCardSpotlight();
                    initPosterTilt();
                }
            } else {
                document.body.classList.remove('has-movie');
            }
        }

        var observer = new MutationObserver(onVisibilityChange);
        observer.observe(content, { attributes: true, attributeFilter: ['class'] });
        onVisibilityChange();
    }

    function initNavDropdowns() {
        var menus = document.querySelectorAll('.media-menu, .user-menu');

        function closeAll(except) {
            menus.forEach(function (menu) {
                if (menu === except) return;
                var drop = menu.querySelector('.media-dropdown, .user-dropdown, .account-dropdown');
                if (drop) drop.classList.remove('open');
                menu.classList.remove('nav-open');
            });
        }

        menus.forEach(function (menu) {
            var trigger = menu.querySelector('.media-menu-trigger, .user-menu-trigger');
            var drop = menu.querySelector('.media-dropdown, .user-dropdown, .account-dropdown');
            if (!trigger || !drop) return;

            trigger.addEventListener('click', function (e) {
                e.stopPropagation();
                var isOpen = drop.classList.contains('open');
                closeAll(null);
                if (!isOpen) {
                    drop.classList.add('open');
                    menu.classList.add('nav-open');
                }
            });
        });

        document.addEventListener('click', function () {
            closeAll(null);
        });

        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') closeAll(null);
        });
    }

    function patchEnrichmentTransition() {
        var STAGGER_MS = 75;
        var ENRICHABLE_IDS = ['directors', 'writers', 'actors'];

        var pendingTmdb = false;
        var pendingTrailer = false;
        var safetyTimer = null;

        function getLogoContainer() {
            return document.querySelector('.info-col .logo-container');
        }

        function revealLogos(force) {
            if (!force && (pendingTmdb || pendingTrailer)) return;
            clearTimeout(safetyTimer);
            var logoC = getLogoContainer();
            if (!logoC) return;
            logoC.style.opacity = '';
            logoC.style.pointerEvents = '';
            var hasVisible = Array.from(logoC.querySelectorAll('a')).some(function (a) {
                return a.style.display && a.style.display !== 'none';
            });
            if (hasVisible) {
                logoC.style.setProperty('--reveal-delay', '0ms');
                logoC.classList.add('heroui-field-enter');
            }
        }

        function clearEnrichState(hasTmdbId) {
            pendingTmdb = false;
            pendingTrailer = false;
            clearTimeout(safetyTimer);
            ENRICHABLE_IDS.forEach(function (id) {
                var el = document.getElementById(id);
                if (!el) return;
                el.classList.remove('heroui-field-enter');
                el.style.removeProperty('--reveal-delay');
            });
            var logoImg = document.getElementById('movie-logo-img');
            if (logoImg) {
                logoImg.style.removeProperty('opacity');
                logoImg.style.removeProperty('transition');
                logoImg.onload = null;
                logoImg.onerror = null;
            }
            var logoC = getLogoContainer();
            if (logoC) {
                logoC.classList.remove('heroui-field-enter');
                logoC.style.removeProperty('--reveal-delay');
                if (hasTmdbId) {
                    logoC.style.opacity = '0';
                    logoC.style.pointerEvents = 'none';
                } else {
                    logoC.style.opacity = '';
                    logoC.style.pointerEvents = '';
                }
            }
        }

        if (typeof window.updateMovieDisplay === 'function') {
            var origUpdate = window.updateMovieDisplay;
            window.updateMovieDisplay = function (data) {
                var hasTmdbId = !!(data && data.tmdb_id);
                clearEnrichState(hasTmdbId);
                origUpdate.apply(this, arguments);
                if (hasTmdbId) {
                    pendingTmdb = true;
                    pendingTrailer = true;
                    safetyTimer = setTimeout(function () { revealLogos(true); }, 6000);
                }
            };
        }

        if (typeof window.handleAsyncMovieDetails === 'function') {
            var origAsync = window.handleAsyncMovieDetails;
            window.handleAsyncMovieDetails = function () {
                var before = {};
                ENRICHABLE_IDS.forEach(function (id) {
                    var el = document.getElementById(id);
                    if (el) before[id] = el.innerHTML;
                });

                var logoImg = document.getElementById('movie-logo-img');
                var logoWasHidden = !logoImg || logoImg.style.display === 'none' || !logoImg.style.display;

                origAsync.apply(this, arguments);

                var changed = 0;
                ENRICHABLE_IDS.forEach(function (id) {
                    var el = document.getElementById(id);
                    if (!el || el.innerHTML === before[id]) return;
                    el.style.setProperty('--reveal-delay', (changed * STAGGER_MS) + 'ms');
                    el.classList.add('heroui-field-enter');
                    changed++;
                });

                if (logoImg && logoWasHidden && logoImg.style.display && logoImg.style.display !== 'none') {
                    logoImg.style.opacity = '0';
                    var revealLogo = function () {
                        logoImg.style.transition = 'opacity 0.45s cubic-bezier(0.16, 1, 0.3, 1)';
                        logoImg.style.opacity = '1';
                    };
                    if (logoImg.complete && logoImg.naturalWidth > 0) {
                        requestAnimationFrame(revealLogo);
                    } else {
                        logoImg.onload = revealLogo;
                        logoImg.onerror = revealLogo;
                    }
                }

                pendingTmdb = false;
                revealLogos(false);
            };
        }

        if (typeof window.handleAsyncTrailer === 'function') {
            var origTrailer = window.handleAsyncTrailer;
            window.handleAsyncTrailer = function () {
                origTrailer.apply(this, arguments);
                pendingTrailer = false;
                revealLogos(false);
            };
        }
    }

    function initCollectionModal() {
        var modal = document.getElementById('collection_modal');
        if (!modal) return;

        function enhanceHeader() {
            if (modal.classList.contains('hidden')) return;
            var header = modal.querySelector('.collection-info-header');
            var h3 = header && header.querySelector('h3');
            if (!h3) return;

            h3.textContent = h3.textContent
                .replace(/^Part of\s+/i, '')
                .replace(/\s+Collection$/i, '');

            if (!header.querySelector('.heroui-collection-label')) {
                var label = document.createElement('span');
                label.className = 'heroui-collection-label';
                label.textContent = 'COLLECTION';
                header.insertBefore(label, h3);
            }
        }

        new MutationObserver(enhanceHeader)
            .observe(modal, { attributes: true, attributeFilter: ['class'] });
    }

    function initCardControls() {
        var filterContainer = document.querySelector('.filter-container');
        var card = document.querySelector('.movie-hero-card');
        if (!filterContainer || !card) return;

        var wrapper = document.createElement('div');
        wrapper.className = 'card-controls';
        wrapper.appendChild(filterContainer);
        card.appendChild(wrapper);
    }

    function initWatchStatusPills() {
        var sel = document.getElementById('watchStatusSelect');
        if (!sel) return;

        var pillBox = document.createElement('div');
        pillBox.className = 'heroui-watch-pills';

        function syncFromSelect() {
            pillBox.querySelectorAll('.heroui-watch-pill').forEach(function (p) {
                p.classList.toggle('active', p.dataset.value === sel.value);
            });
        }

        var LABELS = { unwatched: 'Unwatched', all: 'All', watched: 'Watched' };
        ['unwatched', 'all', 'watched'].forEach(function (val) {
            var pill = document.createElement('button');
            pill.type = 'button';
            pill.className = 'heroui-watch-pill';
            pill.dataset.value = val;
            pill.textContent = LABELS[val];
            if (sel.value === val) pill.classList.add('active');

            pill.addEventListener('click', function () {
                if (sel.value === val) return;
                sel.value = val;
                sel.dispatchEvent(new Event('change', { bubbles: true }));
                syncFromSelect();
            });

            pillBox.appendChild(pill);
        });

        sel.style.display = 'none';
        sel.parentNode.insertBefore(pillBox, sel);

        var clearBtn = document.getElementById('clearFilter');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                setTimeout(syncFromSelect, 0);
            });
        }
    }

    function init() {
        initMovieContentObserver();
        initNavDropdowns();
        initMovieLoadTransition();
        patchEnrichmentTransition();
        initCardControls();
        initWatchStatusPills();
        initCollectionModal();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
