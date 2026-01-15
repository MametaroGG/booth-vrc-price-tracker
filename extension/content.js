// content.js
(async function () {
    const productId = window.location.pathname.split('/').pop();
    if (!productId || isNaN(productId)) return;

    // Sharding: Use first 3 characters of ID for directory structure
    const shard = productId.substring(0, 3);
    const GITHUB_PAGES_URL = `https://MametaroGG.github.io/booth-vrc-price-tracker/data/${shard}/${productId}.json`;

    async function fetchPriceHistory() {
        try {
            const response = await fetch(GITHUB_PAGES_URL);
            if (!response.ok) return null;
            return await response.json();
        } catch (e) {
            console.error('[BOOTH Price Tracker] Failed to fetch history:', e);
            return null;
        }
    }

    function injectTracker(data) {
        // Find price elements on the page
        const priceElements = document.querySelectorAll('.variation-price');
        if (priceElements.length === 0) return;

        // Create container for the graph
        const container = document.createElement('div');
        container.className = 'booth-price-tracker-container';

        const title = document.createElement('div');
        title.className = 'booth-price-tracker-title';
        title.innerHTML = '📈 価格推移 (Price History)';
        container.appendChild(title);

        const canvas = document.createElement('canvas');
        canvas.className = 'booth-price-tracker-canvas';
        container.appendChild(canvas);

        // Inject into the first variation or a prominent place
        const target = document.querySelector('.item-detail, .variations');
        if (target) {
            target.prepend(container);
        } else {
            priceElements[0].closest('li')?.appendChild(container) || document.body.appendChild(container);
        }

        drawChart(canvas, data);

        // Check for sale
        const latestInfo = data[data.length - 1];
        const prices = data.map(d => d.price);
        const avgPrice = prices.reduce((a, b) => a + b, 0) / prices.length;

        if (latestInfo.price < avgPrice) {
            priceElements.forEach(el => {
                const badge = document.createElement('span');
                badge.className = 'booth-sale-badge';
                badge.textContent = 'SALE?';
                el.appendChild(badge);
            });
        }
    }

    function drawChart(canvas, data) {
        const ctx = canvas.getContext('2d');
        const containerWidth = canvas.clientWidth || 300;
        const containerHeight = canvas.clientHeight || 150;
        canvas.width = containerWidth * window.devicePixelRatio;
        canvas.height = containerHeight * window.devicePixelRatio;
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

        const prices = data.map(d => d.price);
        const minPrice = Math.min(...prices);
        const maxPrice = Math.max(...prices);
        const padding = 20;

        const chartHeight = containerHeight - padding * 2;
        const chartWidth = containerWidth - padding * 2;

        const getY = (price) => {
            if (maxPrice === minPrice) return containerHeight / 2;
            return containerHeight - padding - ((price - minPrice) / (maxPrice - minPrice)) * chartHeight;
        };

        const getX = (index) => {
            if (data.length <= 1) return containerWidth / 2;
            return padding + (index / (data.length - 1)) * chartWidth;
        };

        // Draw background lines
        ctx.strokeStyle = '#f0f0f0';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding, getY(minPrice));
        ctx.lineTo(padding + chartWidth, getY(minPrice));
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(padding, getY(maxPrice));
        ctx.lineTo(padding + chartWidth, getY(maxPrice));
        ctx.stroke();

        // Draw labels
        ctx.fillStyle = '#999';
        ctx.font = '10px sans-serif';
        ctx.fillText(`¥${minPrice.toLocaleString()}`, 0, getY(minPrice));
        ctx.fillText(`¥${maxPrice.toLocaleString()}`, 0, getY(maxPrice));

        // Draw line
        ctx.beginPath();
        ctx.strokeStyle = '#fc4d50';
        ctx.lineWidth = 2;
        ctx.lineJoin = 'round';
        ctx.lineCap = 'round';

        data.forEach((d, i) => {
            const x = getX(i);
            const y = getY(d.price);
            if (i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        });
        ctx.stroke();

        // Dots
        data.forEach((d, i) => {
            const x = getX(i);
            const y = getY(d.price);
            ctx.fillStyle = '#fc4d50';
            ctx.beginPath();
            ctx.arc(x, y, 3, 0, Math.PI * 2);
            ctx.fill();
        });
    }

    const history = await fetchPriceHistory();
    if (history && history.length > 0) {
        injectTracker(history);
    }
})();
