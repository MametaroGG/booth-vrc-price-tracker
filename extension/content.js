// content.js
(async function () {
    console.log('[Boopa] Script initialized for ID:', window.location.pathname);
    const pathSegments = window.location.pathname.split('/');
    const itemsIndex = pathSegments.indexOf('items');
    const productId = itemsIndex !== -1 ? pathSegments[itemsIndex + 1] : null;
    console.log('[Boopa] Extracted Product ID:', productId);
    if (!productId || isNaN(productId)) {
        console.log('[Boopa] Invalid Product ID, stopping.');
        return;
    }

    // Sharding: Use first 3 characters of ID for directory structure
    const shard = productId.toString().substring(0, 3);
    const GITHUB_PAGES_URL = `https://mametarogg.github.io/booth-vrc-price-tracker/data/${shard}/${productId}.json?t=${new Date().getTime()}`;

    function isTargetProduct() {
        // Collect category links, but exclude those in sidebars/recommendations
        const allBrowseLinks = Array.from(document.querySelectorAll('a[href*="/browse/"]'));
        const validCategoryLinks = allBrowseLinks.filter(a => {
            const parent = a.closest('.recommend, .item-recommend, .other-items, .shop-items, .related-tags, .sidebar, .l-side, footer');
            return !parent;
        });

        const excludedCategories = [
            'ハードウェア・ガジェット', 'Hardware / Gadgets', 'Hardware & Gadgets',
            '写真作品', 'Photography',
            '素材データ', 'Materials',
            '小説・書籍', 'Novels / Books',
            'ゲーム', 'Games'
        ];

        // 1. Check for Excluded Categories first
        const isExcluded = validCategoryLinks.some(a => {
            const text = a.textContent.trim();
            return excludedCategories.includes(text);
        });

        if (isExcluded) {
            console.log('[Boopa] Excluded category detected, skipping.');
            return false;
        }

        const allowedCategories = [
            '3Dモデル', '3D Models',
            'ソフトウェア', 'Software'
        ];

        // 2. Check for Allowed Categories
        const isAllowedCategory = validCategoryLinks.some(a => {
            const text = a.textContent.trim();
            return allowedCategories.includes(text);
        });

        if (!isAllowedCategory) {
            console.log('[Boopa] Category not in whitelist (3D Models/Software), skipping.');
            return false;
        }
        // Tag check: specific tag links
        const tagLinks = Array.from(document.querySelectorAll('a[href*="tags"]'));
        const hasVrcTag = tagLinks.some(a => {
            const text = a.textContent.trim().toLowerCase();
            return text === 'vrchat' || text === 'vrchat想定';
        });

        // Title check: h2 usually contains the title
        const title = document.querySelector('h2')?.innerText.toLowerCase() || '';
        const hasVrcTitle = title.includes('vrchat') || title.includes('vrc');

        // Combined stricter check: Must have explicit Tag OR Title mentioning VRChat.
        // Removed broad document.body check to avoid false positives from footers/ads.
        return hasVrcTag || hasVrcTitle;
    }

    async function fetchPriceHistory() {
        const target = isTargetProduct();
        try {
            // Using sendMessage to bypass CORS/CSP issues in content script
            const result = await new Promise((resolve) => {
                chrome.runtime.sendMessage(
                    { type: 'FETCH_PRICE_HISTORY', url: GITHUB_PAGES_URL },
                    (response) => {
                        if (chrome.runtime.lastError) {
                            console.error('[Boopa] Message error:', chrome.runtime.lastError);
                            resolve({ success: false });
                        } else {
                            resolve(response);
                        }
                    }
                );
            });

            if (!result || !result.success) {
                if (target) {
                    console.log('[Boopa] Target product found but fetch failed, showing demo data.');
                    return {
                        isDemo: true,
                        data: {
                            "商品1": [
                                { "date": "2026-01-01", "price": 6000, "is_sale": false },
                                { "date": "2026-01-15", "price": 5000, "is_sale": true }
                            ],
                            "商品2": [
                                { "date": "2026-01-01", "price": 2000, "is_sale": false },
                                { "date": "2026-01-15", "price": 2000, "is_sale": false }
                            ]
                        }
                    };
                }
                return null;
            }

            const json = result.data;
            // Handle both old and new formats (new has .variations)
            return {
                isDemo: false,
                data: json.variations || { "標準価格": json }
            };
        } catch (e) {
            console.error('[Boopa] fetchPriceHistory exception:', e);
            return null;
        }
    }

    function injectTracker(result) {
        console.log('[Boopa] Injecting tracker. isDemo:', result.isDemo);
        const variations = result.data;
        const isDemo = result.isDemo;
        let currentRange = 'all';

        // Find price elements on the page
        const priceElements = document.querySelectorAll('.variation-price');
        if (priceElements.length === 0) return;

        // Create container for the graph
        const container = document.createElement('div');
        container.className = 'booth-price-tracker-container';

        const titleArea = document.createElement('div');
        titleArea.className = 'booth-price-tracker-title';
        const chartIcon = `
            <svg class="booth-price-tracker-icon" xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="22 7 13.5 15.5 8.5 10.5 2 17"></polyline>
                <polyline points="16 7 22 7 22 13"></polyline>
            </svg>
        `;

        titleArea.innerHTML = isDemo
            ? `<span>${chartIcon} 価格推移 <small style="color: #999; font-weight: normal;">(収集待ち: デモ表示)</small></span>`
            : `<span>${chartIcon} 価格推移</span>`;

        const canvas = document.createElement('canvas');
        canvas.className = 'booth-price-tracker-canvas';
        container.appendChild(canvas);

        // Only show controls if NOT in demo mode
        if (!isDemo) {
            const selector = document.createElement('div');
            selector.className = 'booth-price-range-selector';

            const ranges = [
                { label: '1日', value: 1 },
                { label: '5日', value: 5 },
                { label: '1か月', value: 30 },
                { label: '6か月', value: 180 },
                { label: '年初来', value: 'ytd' },
                { label: '1年', value: 365 },
                { label: '5年', value: 1825 },
                { label: '最大', value: 'all' }
            ];

            const legendToggle = document.createElement('div');
            legendToggle.className = 'booth-legend-toggle';
            legendToggle.innerHTML = '<span>▼</span> 商品一覧を表示';
            container.appendChild(legendToggle);

            const legendArea = document.createElement('div');
            legendArea.className = 'booth-price-legend collapsed'; // Default to collapsed
            legendArea.style.cssText = 'display: flex; flex-wrap: wrap; gap: 10px; margin-top: 10px; font-size: 11px; opacity: 0.8; color: inherit;';
            container.appendChild(legendArea);

            legendToggle.onclick = () => {
                const isCollapsed = legendArea.classList.toggle('collapsed');
                legendToggle.querySelector('span').textContent = isCollapsed ? '▼' : '▲';
                legendToggle.querySelector('span').nextSibling.textContent = isCollapsed ? ' 商品一覧を表示' : ' 商品一覧を閉じる';
            };

            const allVarNames = Object.keys(variations);
            // Initialize all as active
            const activeVariations = new Set(allVarNames);

            // Map to keep track of legend items to update styles
            const legendItems = {};

            allVarNames.forEach((vName, idx) => {
                const color = COLORS[idx % COLORS.length];
                const item = document.createElement('div');
                item.style.cssText = 'display: flex; align-items: center; gap: 4px; cursor: pointer; padding: 2px 4px; border-radius: 4px; transition: opacity 0.2s, background 0.2s; user-select: none;';
                item.innerHTML = `<span style="width: 8px; height: 8px; background: ${color}; border-radius: 50%;"></span><span>${vName}</span>`;

                // Helper to update style based on active state
                const updateStyle = () => {
                    item.style.opacity = activeVariations.has(vName) ? '1.0' : '0.4';
                    item.style.textDecoration = activeVariations.has(vName) ? 'none' : 'line-through';
                };

                // Click Interaction: Toggle visibility
                item.onclick = () => {
                    if (activeVariations.has(vName)) {
                        activeVariations.delete(vName);
                    } else {
                        activeVariations.add(vName);
                    }
                    updateStyle();
                    // Redraw with current active set
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo);
                };

                // Hover Interaction: Highlight specific variation TEMPORARILY
                item.onmouseenter = () => {
                    if (!activeVariations.has(vName)) return; // Don't highlight if hidden
                    item.style.background = 'rgba(128, 128, 128, 0.1)';
                    drawChart(canvas, variations, currentRange, vName, activeVariations, isDemo);
                };
                item.onmouseleave = () => {
                    item.style.background = 'transparent';
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo);
                };

                updateStyle();
                legendItems[vName] = item;
                legendArea.appendChild(item);
            });

            ranges.forEach(r => {
                const btn = document.createElement('button');
                btn.className = 'booth-price-range-btn' + (r.value === currentRange ? ' active' : '');
                btn.textContent = r.label;
                btn.onclick = () => {
                    currentRange = r.value;
                    container.querySelectorAll('.booth-price-range-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    drawChart(canvas, variations, currentRange, null, activeVariations, isDemo);
                };
                selector.appendChild(btn);
            });

            titleArea.appendChild(selector);
        }
        container.appendChild(titleArea);

        // Inject into the first variation or a prominent place
        const target = document.querySelector('.item-detail, .variations');
        if (target) {
            target.prepend(container);
        } else {
            priceElements[0].closest('li')?.appendChild(container) || document.body.appendChild(container);
        }

        drawChart(canvas, variations, currentRange, null, isDemo ? null : new Set(Object.keys(variations)), isDemo);
    }

    const COLORS = ['#fc4d50', '#4a90e2', '#7fb800', '#f5a623', '#9013fe', '#bd10e0'];

    function drawChart(canvas, variations, range, highlightName, activeVariations = null, isDemo = false) {
        const ctx = canvas.getContext('2d');
        const containerWidth = canvas.clientWidth || 300;
        const containerHeight = canvas.clientHeight || 150;
        canvas.width = containerWidth * window.devicePixelRatio;
        canvas.height = containerHeight * window.devicePixelRatio;
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        ctx.scale(window.devicePixelRatio, window.devicePixelRatio);

        if (isDemo) {
            ctx.fillStyle = '#999';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('データ収集はされていません。', containerWidth / 2, containerHeight / 2);
            return;
        }

        const now = new Date();
        const filteredVars = {};
        let allPoints = [];

        Object.keys(variations).forEach(vName => {
            // Skip if not active (and active set is provided)
            if (activeVariations && !activeVariations.has(vName)) return;

            let data = variations[vName];
            if (range !== 'all') {
                let cutoff = new Date();
                if (range === 'ytd') {
                    cutoff = new Date(now.getFullYear(), 0, 1);
                } else {
                    cutoff.setDate(now.getDate() - range);
                }
                data = data.filter(d => new Date(d.date) >= cutoff);
            }
            if (data.length > 0) {
                filteredVars[vName] = data;
                allPoints = allPoints.concat(data);
            }
        });

        if (allPoints.length === 0) {
            ctx.fillStyle = '#999';
            ctx.font = '12px sans-serif';
            ctx.textAlign = 'center';
            ctx.fillText('データがありません', containerWidth / 2, containerHeight / 2);
            return;
        }

        const prices = allPoints.map(d => d.price);
        const minPrice = Math.min(...prices) * 0.95;
        const maxPrice = Math.max(...prices) * 1.05;
        const padding = 35;
        const bottomPadding = 30;

        const chartHeight = containerHeight - padding - bottomPadding;
        const chartWidth = containerWidth - padding * 2;

        const allDates = [...new Set(allPoints.map(d => d.date))].sort();
        const startDate = new Date(allDates[0]);
        const endDate = new Date(allDates[allDates.length - 1]);
        const timeRange = (endDate - startDate) || 1;

        const getX = (dateStr) => {
            if (timeRange === 1) return padding + chartWidth / 2;
            const d = new Date(dateStr);
            return padding + ((d - startDate) / timeRange) * chartWidth;
        };

        const getY = (price) => {
            if (maxPrice === minPrice) return padding + chartHeight / 2;
            return padding + chartHeight - ((price - minPrice) / (maxPrice - minPrice)) * chartHeight;
        };

        // Detect text color from computed style for labels
        const compStyle = window.getComputedStyle(canvas.parentElement);
        const labelColor = compStyle.color || '#999';

        // Draw background lines
        ctx.strokeStyle = 'rgba(128, 128, 128, 0.2)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(padding, getY(minPrice / 0.95));
        ctx.lineTo(padding + chartWidth, getY(minPrice / 0.95));
        ctx.stroke();
        ctx.beginPath();
        ctx.moveTo(padding, getY(maxPrice / 1.05));
        ctx.lineTo(padding + chartWidth, getY(maxPrice / 1.05));
        ctx.stroke();

        ctx.fillStyle = labelColor;
        ctx.globalAlpha = 0.6;
        ctx.font = '9px sans-serif';
        ctx.textAlign = 'left';
        ctx.fillText(`¥${Math.round(minPrice / 0.95).toLocaleString()}`, 0, getY(minPrice / 0.95));
        ctx.fillText(`¥${Math.round(maxPrice / 1.05).toLocaleString()}`, 0, getY(maxPrice / 1.05));

        ctx.textAlign = 'left';
        ctx.fillText(allDates[0].replace(/-/g, '/'), padding, containerHeight - 10);
        if (allDates.length > 1) {
            ctx.textAlign = 'right';
            ctx.fillText(allDates[allDates.length - 1].replace(/-/g, '/'), padding + chartWidth, containerHeight - 10);
        }

        const pointsToHover = [];
        const allVarNames = Object.keys(variations); // Stable order for colors based on full data set

        Object.keys(filteredVars).forEach((vName) => {
            const data = filteredVars[vName];
            const colorIndex = allVarNames.indexOf(vName);
            const color = COLORS[colorIndex % COLORS.length];

            // Determine visibility/emphasis
            let alpha = 0.8;
            let lineWidth = 2;
            if (highlightName) {
                if (vName === highlightName) {
                    alpha = 1.0;
                    lineWidth = 3; // Emphasize
                } else {
                    return; // Strictly hide others
                }
            }

            ctx.globalAlpha = alpha;
            ctx.beginPath();
            ctx.strokeStyle = color;
            ctx.lineWidth = lineWidth;
            ctx.lineJoin = 'round';
            data.forEach((d, i) => {
                const x = getX(d.date);
                const y = getY(d.price);
                if (i === 0) ctx.moveTo(x, y);
                else ctx.lineTo(x, y);
                pointsToHover.push({ x, y, data: d, vName, color });
            });
            ctx.stroke();

            data.forEach(d => {
                ctx.fillStyle = color;
                ctx.beginPath();
                ctx.arc(getX(d.date), getY(d.price), highlightName === vName ? 4 : 2.5, 0, Math.PI * 2);
                ctx.fill();
            });
            ctx.globalAlpha = 1.0;
        });

        let tooltip = canvas.parentElement.querySelector('.booth-chart-tooltip');
        if (!tooltip) {
            tooltip = document.createElement('div');
            tooltip.className = 'booth-chart-tooltip';
            canvas.parentElement.appendChild(tooltip);
        }

        // Attach current points to canvas for the event listener to access
        canvas.pointsToHover = pointsToHover;

        if (!canvas.dataset.hasListener) {
            canvas.addEventListener('mousemove', (e) => {
                const rect = canvas.getBoundingClientRect();
                const mx = e.clientX - rect.left;
                const my = e.clientY - rect.top;

                let hoveredPoint = null;
                let minDist = 20;

                // Use the latest points attached to the canvas
                const currentPoints = canvas.pointsToHover || [];

                currentPoints.forEach(p => {
                    const dx = mx - p.x;
                    const dy = my - p.y;
                    const dist = Math.sqrt(dx * dx + dy * dy);
                    if (dist < minDist) {
                        minDist = dist;
                        hoveredPoint = p;
                    }
                });

                if (hoveredPoint) {
                    tooltip.style.display = 'block';
                    tooltip.style.left = `${canvas.offsetLeft + hoveredPoint.x}px`;
                    tooltip.style.top = `${canvas.offsetTop + hoveredPoint.y - 5}px`;
                    tooltip.style.borderLeft = `3px solid ${hoveredPoint.color}`;
                    const dateStr = hoveredPoint.data.date.replace(/-/g, '/');
                    const saleBadge = hoveredPoint.data.is_sale
                        ? '<span style="background:#ff3838; color:white; padding:1px 4px; border-radius:3px; font-size:10px; margin-left:5px; font-weight:bold; vertical-align: middle;">SALE</span>'
                        : '';
                    tooltip.innerHTML = `<strong>${hoveredPoint.vName}</strong>${saleBadge}<br>${dateStr}<br>¥${hoveredPoint.data.price.toLocaleString()}`;
                } else {
                    tooltip.style.display = 'none';
                }
            });

            canvas.addEventListener('mouseleave', () => tooltip.style.display = 'none');
            canvas.dataset.hasListener = 'true';
        }
    }

    async function main(retryCount = 0) {
        const result = await fetchPriceHistory();
        if (result && result.data && Object.keys(result.data).length > 0) {
            injectTracker(result);
        } else if (retryCount < 3) {
            console.log(`[Boopa] No data/target found, retrying... (${retryCount + 1}/3)`);
            setTimeout(() => main(retryCount + 1), 1000);
        } else {
            console.log('[Boopa] Giving up after 3 retries.');
        }
    }

    main();
})();
