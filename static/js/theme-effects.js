(function () {
    'use strict';

    if (!document.body.classList.contains('heroui-theme')) return;

    const isPosterPage = document.body.classList.contains('poster-page');

    function injectOverlayDOM() {
        if (isPosterPage) return;

        const spotlight = document.createElement('div');
        spotlight.className = 'spotlight-overlay';
        document.body.appendChild(spotlight);

        const aurora = document.createElement('div');
        aurora.className = 'aurora-bg';
        document.body.appendChild(aurora);
    }

    function initSpotlight() {
        if (isPosterPage) return;

        let rafId;
        document.addEventListener('mousemove', function (e) {
            cancelAnimationFrame(rafId);
            rafId = requestAnimationFrame(function () {
                var x = (e.clientX / window.innerWidth * 100).toFixed(1) + '%';
                var y = (e.clientY / window.innerHeight * 100).toFixed(1) + '%';
                document.body.style.setProperty('--mouse-x', x);
                document.body.style.setProperty('--mouse-y', y);
            });
        });
    }

    var SPARKLE_COLORS = ['#6366f1', '#818cf8', '#06b6d4', '#e5a00d', '#c4b5fd', '#ffffff'];

    function spawnSparkles(element) {
        var rect = element.getBoundingClientRect();
        var cx = rect.left + rect.width / 2;
        var cy = rect.top + rect.height / 2;
        var count = 8;

        for (var i = 0; i < count; i++) {
            var particle = document.createElement('span');
            particle.className = 'sparkle-particle';

            var angle = (i / count) * 360;
            var distance = 18 + Math.random() * 28;
            var dx = Math.cos(angle * Math.PI / 180) * distance;
            var dy = Math.sin(angle * Math.PI / 180) * distance;
            var color = SPARKLE_COLORS[Math.floor(Math.random() * SPARKLE_COLORS.length)];

            particle.style.cssText =
                'left:' + cx + 'px;' +
                'top:' + cy + 'px;' +
                'background:' + color + ';' +
                '--dx:' + dx + 'px;' +
                '--dy:' + dy + 'px;';

            document.body.appendChild(particle);
            setTimeout(function (p) { p.remove(); }, 650, particle);
        }
    }

    function initSparkles() {
        document.querySelectorAll('.button, .watch-button, .login-button').forEach(function (btn) {
            btn.addEventListener('mouseenter', function () { spawnSparkles(btn); });
        });
    }

    function initTiltCards() {
        if (isPosterPage) return;

        document.querySelectorAll('.movie-card, .settings-section').forEach(function (card) {
            card.classList.add('tilt-card');

            card.addEventListener('mousemove', function (e) {
                var rect = card.getBoundingClientRect();
                var cx = rect.left + rect.width / 2;
                var cy = rect.top + rect.height / 2;
                var rx = ((e.clientY - cy) / (rect.height / 2)) * -7;
                var ry = ((e.clientX - cx) / (rect.width / 2)) * 7;
                card.style.transform =
                    'perspective(800px) rotateX(' + rx + 'deg) rotateY(' + ry + 'deg) translateZ(4px)';
            });

            card.addEventListener('mouseleave', function () {
                card.style.transform =
                    'perspective(800px) rotateX(0deg) rotateY(0deg) translateZ(0)';
            });
        });
    }

    function initEntranceAnimations() {
        if (isPosterPage) return;

        var targets = document.querySelectorAll(
            '.settings-section, .movie-card, .collection-card, .login-card, .setup-card'
        );

        if (!('IntersectionObserver' in window)) {
            targets.forEach(function (el) { el.classList.add('fade-in-up'); });
            return;
        }

        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add('fade-in-up');
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.08 });

        targets.forEach(function (el) { observer.observe(el); });
    }

    function initGlowCTA() {
        var cta = document.querySelector('#watchButton, .button[id*="watch"], .button[id*="next"]');
        if (cta) cta.classList.add('button-glow');
    }

    function initStaggerLists() {
        var selectors = [
            '#container_list_of_clients > *',
            '.movie-grid > .movie-card',
            '.collection-grid > .collection-card'
        ];
        selectors.forEach(function (sel) {
            document.querySelectorAll(sel).forEach(function (item) {
                item.classList.add('stagger-item', 'fade-in-up');
            });
        });
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

    function initCollectionGridObserver() {
        var grid = document.getElementById('collection-grid');
        if (!grid) return;

        new MutationObserver(function (mutations) {
            mutations.forEach(function (m) {
                m.addedNodes.forEach(function (node) {
                    if (node.nodeType === 1 && node.classList.contains('collection-card')) {
                        node.classList.add('stagger-item', 'fade-in-up');
                    }
                });
            });
        }).observe(grid, { childList: true });
    }

    function init() {
        injectOverlayDOM();
        initSpotlight();
        initSparkles();
        initTiltCards();
        initEntranceAnimations();
        initGlowCTA();
        initStaggerLists();
        initCollectionModal();
        initCollectionGridObserver();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
}());
