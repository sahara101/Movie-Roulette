(function () {
    'use strict';

    const W   = 720;
    const PAD = 52;

    const POST_W = 444;
    const POST_H = Math.round(POST_W * 3 / 2);
    const POST_X = Math.round((W - POST_W) / 2);
    const POST_Y = PAD;

    const FONT = 'Inter,-apple-system,BlinkMacSystemFont,sans-serif';

    const TITLE_SIZE   = 56;
    const TITLE_LINE_H = TITLE_SIZE + 8;
    const LABEL_SIZE   = 20;
    const META_SIZE    = 26;
    const BAR_H        = 6;
    const PROG_SIZE    = 20;
    const BRAND_SIZE   = 16;

    const GAP_POSTER_TEXT = 36;
    const GAP_LABEL       = 14;
    const GAP_TITLE       = 14;
    const GAP_META        = 28;
    const GAP_BAR         = 12;
    const GAP_PROG        = 22;
    const BOTTOM_PAD      = 52;

    function loadImage(src) {
        return new Promise(function (resolve, reject) {
            const img = new Image();
            img.onload  = function () { resolve(img); };
            img.onerror = function () { reject(new Error('img load failed')); };
            img.src = src;
        });
    }

    function rrect(ctx, x, y, w, h, r) {
        r = Math.min(r, w / 2, h / 2);
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.arcTo(x + w, y,     x + w, y + h, r);
        ctx.arcTo(x + w, y + h, x,     y + h, r);
        ctx.arcTo(x,     y + h, x,     y,     r);
        ctx.arcTo(x,     y,     x + w, y,     r);
        ctx.closePath();
    }

    function wrapText(ctx, text, maxW, maxLines) {
        const words = text.split(' ');
        const lines = [];
        let line = '';
        let i = 0;
        for (; i < words.length; i++) {
            const test = line ? line + ' ' + words[i] : words[i];
            if (ctx.measureText(test).width > maxW && line) {
                lines.push(line);
                line = words[i];
                if (lines.length >= maxLines) { i++; break; }
            } else {
                line = test;
            }
        }
        const truncated = i < words.length;
        if (line && lines.length < maxLines) lines.push(line);
        if (truncated && lines.length > 0) {
            let last = lines[lines.length - 1];
            while (last.length > 0 && ctx.measureText(last + '\u2026').width > maxW) {
                last = last.slice(0, -1);
            }
            lines[lines.length - 1] = last.trimEnd() + '\u2026';
        }
        return lines;
    }

    function boxBlur(ctx, w, h, r) {
        const id  = ctx.getImageData(0, 0, w, h);
        const src = id.data;
        const buf = new Uint8ClampedArray(src.length);
        const d   = r + r + 1;

        for (let y = 0; y < h; y++) {
            const row = y * w;
            let rs = 0, gs = 0, bs = 0;
            for (let kx = -r; kx <= r; kx++) {
                const p = (row + Math.max(0, kx)) * 4;
                rs += src[p]; gs += src[p + 1]; bs += src[p + 2];
            }
            for (let x = 0; x < w; x++) {
                const i  = (row + x) * 4;
                buf[i]     = rs / d | 0;
                buf[i + 1] = gs / d | 0;
                buf[i + 2] = bs / d | 0;
                buf[i + 3] = 255;
                const xR = (row + Math.max(0,     x - r))     * 4;
                const xA = (row + Math.min(w - 1, x + r + 1)) * 4;
                rs += src[xA] - src[xR];
                gs += src[xA + 1] - src[xR + 1];
                bs += src[xA + 2] - src[xR + 2];
            }
        }

        for (let x = 0; x < w; x++) {
            let rs = 0, gs = 0, bs = 0;
            for (let ky = -r; ky <= r; ky++) {
                const p = (Math.max(0, ky) * w + x) * 4;
                rs += buf[p]; gs += buf[p + 1]; bs += buf[p + 2];
            }
            for (let y = 0; y < h; y++) {
                const i  = (y * w + x) * 4;
                src[i]     = rs / d | 0;
                src[i + 1] = gs / d | 0;
                src[i + 2] = bs / d | 0;
                src[i + 3] = 255;
                const yR = (Math.max(0,     y - r)     * w + x) * 4;
                const yA = (Math.min(h - 1, y + r + 1) * w + x) * 4;
                rs += buf[yA] - buf[yR];
                gs += buf[yA + 1] - buf[yR + 1];
                bs += buf[yA + 2] - buf[yR + 2];
            }
        }

        ctx.putImageData(id, 0, 0);
    }

    function drawCoverImage(ctx, img, dx, dy, dw, dh) {
        const imgR = img.width / img.height;
        const boxR = dw / dh;
        let sx, sy, sw, sh;
        if (imgR > boxR) {
            sh = img.height; sw = Math.round(sh * boxR);
            sx = Math.round((img.width - sw) / 2); sy = 0;
        } else {
            sw = img.width; sh = Math.round(sw / boxR);
            sx = 0; sy = Math.round((img.height - sh) / 2);
        }
        ctx.drawImage(img, sx, sy, sw, sh, dx, dy, dw, dh);
    }

    async function buildShareCanvas(data) {
        const DPR = 2;

        await document.fonts.ready;

        const [pi, bi] = await Promise.allSettled([
            data.poster_proxy   ? loadImage(data.poster_proxy)   : Promise.reject(),
            data.backdrop_proxy ? loadImage(data.backdrop_proxy) : Promise.reject(),
        ]);
        const posterImg   = pi.status === 'fulfilled' ? pi.value : null;
        const backdropImg = bi.status === 'fulfilled' ? bi.value : null;

        const mCtx = document.createElement('canvas').getContext('2d');
        mCtx.font = 'bold ' + TITLE_SIZE + 'px ' + FONT;
        const titleLines = wrapText(mCtx, data.title || '', W - PAD * 2, 3);

        const contentH = GAP_POSTER_TEXT
                       + LABEL_SIZE   + GAP_LABEL
                       + titleLines.length * TITLE_LINE_H + GAP_TITLE
                       + META_SIZE    + GAP_META
                       + BAR_H        + GAP_BAR
                       + PROG_SIZE    + GAP_PROG
                       + BRAND_SIZE   + BOTTOM_PAD;

        const H = POST_Y + POST_H + contentH;

        const canvas = document.createElement('canvas');
        canvas.width  = W * DPR;
        canvas.height = H * DPR;
        const ctx = canvas.getContext('2d');
        ctx.scale(DPR, DPR);
        ctx.imageSmoothingEnabled = true;
        ctx.imageSmoothingQuality = 'high';

        ctx.fillStyle = '#09090b';
        ctx.fillRect(0, 0, W, H);

        const bgImg = backdropImg || posterImg;
        if (bgImg) {
            const iw = Math.max(4, Math.round(W * DPR / 16));
            const ih = Math.max(4, Math.round(H * DPR / 16));
            const tmp = document.createElement('canvas');
            tmp.width  = iw;
            tmp.height = ih;
            const tc = tmp.getContext('2d');
            tc.imageSmoothingEnabled = true;
            tc.imageSmoothingQuality = 'high';
            drawCoverImage(tc, bgImg, 0, 0, iw, ih);

            boxBlur(tc, iw, ih, 8);
            boxBlur(tc, iw, ih, 8);
            boxBlur(tc, iw, ih, 8);

            ctx.save();
            ctx.filter = 'saturate(1.8)';
            ctx.drawImage(tmp, 0, 0, W, H);
            ctx.restore();

            ctx.fillStyle = 'rgba(0,0,0,0.75)';
            ctx.fillRect(0, 0, W, H);

            const vig = ctx.createRadialGradient(W / 2, H * 0.35, 0, W / 2, H * 0.35, H * 0.82);
            vig.addColorStop(0, 'rgba(0,0,0,0)');
            vig.addColorStop(1, 'rgba(0,0,0,0.35)');
            ctx.fillStyle = vig;
            ctx.fillRect(0, 0, W, H);
        } else {
            (function () {
                const g = ctx.createRadialGradient(W * 0.1, H * 0.15, 0, W * 0.1, H * 0.15, W * 0.9);
                g.addColorStop(0, 'rgba(99,102,241,0.55)');
                g.addColorStop(1, 'rgba(99,102,241,0)');
                ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
            }());
            (function () {
                const g = ctx.createRadialGradient(W * 0.9, H * 0.78, 0, W * 0.9, H * 0.78, W * 0.85);
                g.addColorStop(0, 'rgba(124,58,237,0.50)');
                g.addColorStop(1, 'rgba(124,58,237,0)');
                ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
            }());
            (function () {
                const g = ctx.createRadialGradient(W * 0.88, H * 0.08, 0, W * 0.88, H * 0.08, W * 0.65);
                g.addColorStop(0, 'rgba(8,145,178,0.38)');
                g.addColorStop(1, 'rgba(8,145,178,0)');
                ctx.fillStyle = g; ctx.fillRect(0, 0, W, H);
            }());
            (function () {
                const S = 24;
                ctx.fillStyle = 'rgba(255,255,255,0.045)';
                for (let x = S / 2; x < W; x += S) {
                    for (let y = S / 2; y < H; y += S) {
                        ctx.beginPath();
                        ctx.arc(x, y, 1, 0, Math.PI * 2);
                        ctx.fill();
                    }
                }
            }());
        }

        if (posterImg) {
            ctx.save();
            ctx.shadowColor   = 'rgba(0,0,0,0.65)';
            ctx.shadowBlur    = 44;
            ctx.shadowOffsetY = 10;
            rrect(ctx, POST_X, POST_Y, POST_W, POST_H, 18);
            ctx.fillStyle = 'rgba(0,0,0,0.01)';
            ctx.fill();
            ctx.restore();

            ctx.save();
            rrect(ctx, POST_X, POST_Y, POST_W, POST_H, 18);
            ctx.clip();
            ctx.drawImage(posterImg, POST_X, POST_Y, POST_W, POST_H);
            ctx.restore();

            ctx.strokeStyle = 'rgba(255,255,255,0.14)';
            ctx.lineWidth   = 1.5;
            rrect(ctx, POST_X, POST_Y, POST_W, POST_H, 18);
            ctx.stroke();
        } else {
            ctx.fillStyle = 'rgba(255,255,255,0.06)';
            rrect(ctx, POST_X, POST_Y, POST_W, POST_H, 18);
            ctx.fill();
        }

        let tY = POST_Y + POST_H + GAP_POSTER_TEXT;

        const dotR = 6;
        ctx.save();
        ctx.shadowColor = 'rgba(74,222,128,0.9)';
        ctx.shadowBlur  = 10;
        ctx.fillStyle   = '#4ade80';
        ctx.beginPath();
        ctx.arc(PAD + dotR, tY + LABEL_SIZE / 2, dotR, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        ctx.font      = '600 ' + LABEL_SIZE + 'px ' + FONT;
        ctx.fillStyle = 'rgba(255,255,255,0.55)';
        ctx.fillText('NOW WATCHING', PAD + dotR * 2 + 10, tY + LABEL_SIZE);
        tY += LABEL_SIZE + GAP_LABEL;

        ctx.font      = 'bold ' + TITLE_SIZE + 'px ' + FONT;
        ctx.fillStyle = '#ffffff';
        for (const line of titleLines) {
            ctx.fillText(line, PAD, tY + TITLE_SIZE);
            tY += TITLE_LINE_H;
        }
        tY += GAP_TITLE;

        const service = data.service
            ? data.service.charAt(0).toUpperCase() + data.service.slice(1)
            : '';
        const metaStr = [data.year, service].filter(Boolean).join('   \u00B7   ');
        ctx.font      = META_SIZE + 'px ' + FONT;
        ctx.fillStyle = 'rgba(255,255,255,0.42)';
        ctx.fillText(metaStr, PAD, tY + META_SIZE);
        tY += META_SIZE + GAP_META;

        const barW = W - PAD * 2;
        const pct  = parseFloat(document.getElementById('nw_pct')?.textContent) / 100 || 0;

        ctx.fillStyle = 'rgba(255,255,255,0.12)';
        rrect(ctx, PAD, tY, barW, BAR_H, 3);
        ctx.fill();

        if (pct > 0) {
            const fg = ctx.createLinearGradient(PAD, 0, PAD + barW, 0);
            fg.addColorStop(0, '#6366f1');
            fg.addColorStop(1, '#7c3aed');
            ctx.fillStyle = fg;
            rrect(ctx, PAD, tY, Math.max(barW * pct, BAR_H * 2), BAR_H, 3);
            ctx.fill();
        }
        tY += BAR_H + GAP_BAR;

        const pctText  = document.getElementById('nw_pct')?.textContent  || '';
        const timeText = document.getElementById('nw_time_left')?.textContent || '';
        const progLine = [pctText, timeText].filter(Boolean).join('   \u00B7   ');
        ctx.font      = PROG_SIZE + 'px ' + FONT;
        ctx.fillStyle = 'rgba(255,255,255,0.30)';
        ctx.fillText(progLine, PAD, tY + PROG_SIZE);
        tY += PROG_SIZE + GAP_PROG;

        ctx.font      = '600 ' + BRAND_SIZE + 'px ' + FONT;
        ctx.fillStyle = 'rgba(255,255,255,0.22)';
        ctx.textAlign = 'right';
        ctx.fillText('Movie Roulette', W - PAD, tY + BRAND_SIZE);
        ctx.textAlign = 'left';

        return canvas;
    }

    async function shareNowWatching() {
        if (typeof nowWatchingData === 'undefined' || !nowWatchingData || !nowWatchingData.active) return;

        const data = nowWatchingData;
        const { title, year, tmdb_id, imdb_id } = data;
        const pct = document.getElementById('nw_pct')?.textContent || '';

        const lines = [
            '\uD83C\uDFAC Now watching: ' + title + (year ? ' (' + year + ')' : '') + (pct ? ' \u00B7 ' + pct + ' through' : '')
        ];
        if (tmdb_id) lines.push('TMDb: https://www.themoviedb.org/movie/' + tmdb_id);
        if (imdb_id) lines.push('IMDb: https://www.imdb.com/title/'       + imdb_id);
        if (imdb_id) lines.push('Trakt: https://trakt.tv/search/imdb/'    + imdb_id);
        const shareText = lines.join('\n');

        try {
            const canvas = await buildShareCanvas(data);

            if (navigator.share) {
                const blob = await new Promise(function (resolve, reject) {
                    canvas.toBlob(function (b) { b ? resolve(b) : reject(new Error('toBlob failed')); }, 'image/png');
                });
                const file = new File([blob], 'now-watching.png', { type: 'image/png' });
                const payload = { text: shareText };
                if (navigator.canShare && navigator.canShare({ files: [file] })) {
                    payload.files = [file];
                }
                try {
                    await navigator.share(payload);
                    return;
                } catch (e) {
                    if (e.name === 'AbortError') return;
                }
            }

            const url = canvas.toDataURL('image/png');
            const a   = document.createElement('a');
            a.href     = url;
            a.download = 'now-watching.png';
            a.click();
            if (typeof showToast === 'function') showToast('Share image saved', 'success');

        } catch (_) {
            try {
                await navigator.clipboard.writeText(shareText);
                if (typeof showToast === 'function') showToast('Copied to clipboard', 'success');
            } catch (_2) {}
        }
    }

    document.getElementById('nw_share_btn')?.addEventListener('click', shareNowWatching);

}());
