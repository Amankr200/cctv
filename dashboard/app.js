const API_BASE = window.location.origin;
const WS_BASE = window.location.origin.replace(/^http/, 'ws');

let currentStore = "STORE_BLR_002";
let ws = null;

// Initialization
document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("storeSelect").addEventListener("change", (e) => {
        currentStore = e.target.value;
        refreshAll();
    });

    refreshAll();
    connectWebSocket();
    
    // Auto refresh slower moving data every 60s
    setInterval(() => {
        fetchHeatmap();
        fetchHealth();
        fetchAnomalies();
    }, 60000);
});

function refreshAll() {
    fetchMetrics();
    fetchFunnel();
    fetchHeatmap();
    fetchAnomalies();
    fetchHealth();
}

// WebSocket Connection
function connectWebSocket() {
    if (ws) ws.close();
    
    const pulse = document.getElementById("connectionPulse");
    const status = document.getElementById("connectionStatus");
    
    status.innerText = "Connecting...";
    pulse.className = "pulse";

    ws = new WebSocket(`${WS_BASE}/ws/live`);
    
    ws.onopen = () => {
        status.innerText = "Live";
        pulse.className = "pulse connected";
    };
    
    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        if (data.type === "METRICS_UPDATE") {
            if (data.data) {
                updateMetricsUI(data.data);
                fetchFunnel();
            } else {
                refreshAll();
            }
        }
    };
    
    ws.onclose = () => {
        status.innerText = "Disconnected";
        pulse.className = "pulse disconnected";
        setTimeout(connectWebSocket, 5000);
    };
    
    ws.onerror = (err) => {
        console.error("WS Error", err);
    };
}

// REST API Fetchers
async function fetchMetrics() {
    try {
        const res = await fetch(`${API_BASE}/stores/${currentStore}/metrics`);
        if (res.ok) {
            const data = await res.json();
            updateMetricsUI(data);
        }
    } catch (e) {
        console.error("Error fetching metrics", e);
    }
}

function updateMetricsUI(data) {
    document.getElementById("valVisitors").innerText = data.unique_visitors.toLocaleString();
    document.getElementById("valConversion").innerText = (data.conversion_rate * 100).toFixed(1) + "%";
    
    if (data.queue_stats) {
        document.getElementById("valQueue").innerText = data.queue_stats.current_queue_depth;
        document.getElementById("valAbandon").innerText = (data.queue_stats.abandonment_rate * 100).toFixed(1) + "%";
        
        const qTrend = document.getElementById("trendQueue");
        qTrend.className = "metric-trend " + (data.queue_stats.current_queue_depth > 3 ? "negative" : "positive");
    }
}

async function fetchFunnel() {
    const container = document.getElementById("funnelContainer");
    try {
        const res = await fetch(`${API_BASE}/stores/${currentStore}/funnel`);
        if (res.ok) {
            const data = await res.json();
            renderFunnel(data.stages);
        }
    } catch (e) {
        container.innerHTML = `<div class="loading">Error loading funnel</div>`;
    }
}

function renderFunnel(stages) {
    const container = document.getElementById("funnelContainer");
    if (!stages || stages.length === 0) {
        container.innerHTML = `<div class="loading">No funnel data available</div>`;
        return;
    }
    
    let html = '';
    const maxCount = stages[0].count || 1;
    
    stages.forEach((stage, i) => {
        const width = Math.max(10, (stage.count / maxCount) * 100);
        
        let dropoffHtml = '';
        if (i > 0 && stages[i-1].count > 0) {
            const dropoff = stages[i-1].count - stage.count;
            const dropPct = (dropoff / stages[i-1].count * 100).toFixed(0);
            dropoffHtml = `<div class="stage-dropoff">-${dropPct}%</div>`;
        } else {
            dropoffHtml = `<div class="stage-dropoff"></div>`;
        }
        
        html += `
            <div class="funnel-stage">
                <div class="stage-label">${stage.stage}</div>
                <div class="stage-bar-container">
                    <div class="stage-bar" style="width: ${width}%">${stage.count}</div>
                </div>
                ${dropoffHtml}
            </div>
        `;
    });
    
    container.innerHTML = html;
}

async function fetchHeatmap() {
    const container = document.getElementById("zoneList");
    try {
        const res = await fetch(`${API_BASE}/stores/${currentStore}/heatmap`);
        if (res.ok) {
            const data = await res.json();
            renderHeatmap(data.zones);
        }
    } catch (e) {
        container.innerHTML = `<div class="loading">Error loading heatmap</div>`;
    }
}

function renderHeatmap(zones) {
    const container = document.getElementById("zoneList");
    if (!zones || zones.length === 0) {
        container.innerHTML = `<div class="loading">No zone data available</div>`;
        return;
    }
    
    // Sort by score desc
    zones.sort((a, b) => b.normalized_score - a.normalized_score);
    
    let html = '';
    zones.forEach(zone => {
        let color = '#74c69d';
        if (zone.normalized_score > 70) color = '#ffb703';
        if (zone.normalized_score > 90) color = '#e63946';
        
        html += `
            <div class="zone-item">
                <div class="zone-info">
                    <div class="zone-name">${zone.zone_name}</div>
                    <div class="zone-stats">
                        <span>Visitors: ${zone.visitor_count}</span>
                        <span>Avg Dwell: ${(zone.avg_dwell_time_ms / 1000).toFixed(0)}s</span>
                    </div>
                </div>
                <div class="zone-score-wrap" style="background: ${color}22; border: 2px solid ${color}; color: ${color}">
                    ${Math.round(zone.normalized_score)}
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

async function fetchAnomalies() {
    const container = document.getElementById("anomalyList");
    try {
        const res = await fetch(`${API_BASE}/stores/${currentStore}/anomalies`);
        if (res.ok) {
            const data = await res.json();
            renderAnomalies(data.anomalies);
        }
    } catch (e) {
        container.innerHTML = `<div class="loading">Error loading anomalies</div>`;
    }
}

function renderAnomalies(anomalies) {
    const container = document.getElementById("anomalyList");
    document.getElementById("alertCount").innerText = anomalies.length;
    
    if (!anomalies || anomalies.length === 0) {
        container.innerHTML = `
            <div class="no-alerts">
                <div class="icon">✨</div>
                <p>All clear. No anomalies detected.</p>
            </div>
        `;
        return;
    }
    
    let html = '';
    anomalies.forEach(a => {
        const time = new Date(a.detected_at).toLocaleTimeString();
        html += `
            <div class="anomaly-item ${a.severity}">
                <div class="anomaly-header">
                    <span class="anomaly-type">${a.anomaly_type.replace(/_/g, ' ')}</span>
                    <span class="anomaly-time">${time}</span>
                </div>
                <div class="anomaly-desc">${a.description}</div>
                <div class="anomaly-action">💡 ${a.suggested_action}</div>
            </div>
        `;
    });
    
    container.innerHTML = html;
}

async function fetchHealth() {
    const container = document.getElementById("healthStats");
    try {
        const res = await fetch(`${API_BASE}/health`);
        if (res.ok) {
            const data = await res.json();
            renderHealth(data);
        }
    } catch (e) {
        container.innerHTML = `<div class="loading">Error loading health</div>`;
    }
}

function renderHealth(data) {
    const container = document.getElementById("healthStats");
    
    let storeStatus = "UNKNOWN";
    let lag = "--";
    
    if (data.stores && data.stores.length > 0) {
        const store = data.stores.find(s => s.store_id === currentStore) || data.stores[0];
        storeStatus = store.status;
        if (store.lag_seconds !== null) {
            lag = store.lag_seconds > 60 ? `${Math.round(store.lag_seconds/60)}m` : `${Math.round(store.lag_seconds)}s`;
        }
    }
    
    const uptime = Math.round(data.uptime_seconds / 60) + "m";
    
    container.innerHTML = `
        <div class="health-item">
            <span class="health-label">System Status</span>
            <span class="health-val ${data.status}">${data.status}</span>
        </div>
        <div class="health-item">
            <span class="health-label">Store Feed</span>
            <span class="health-val ${storeStatus}">${storeStatus}</span>
        </div>
        <div class="health-item">
            <span class="health-label">Data Lag</span>
            <span class="health-val">${lag}</span>
        </div>
        <div class="health-item">
            <span class="health-label">Uptime</span>
            <span class="health-val">${uptime}</span>
        </div>
        <div class="health-item">
            <span class="health-label">Version</span>
            <span class="health-val">${data.version}</span>
        </div>
    `;
}
