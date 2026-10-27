/* One subscription per selected patient. All measurements come from the server. */
(() => {
    "use strict";
    const patients = JSON.parse(document.getElementById("dashboard-data").textContent);
    if (!patients.length) return;
    const byId = new Map(patients.map(patient => [patient.id, patient]));
    const buttons = [...document.querySelectorAll("[data-patient-id]")];
    const state = document.getElementById("reading-state");
    const status = document.getElementById("connection-status");
    const MAX_RECENT_READINGS = 20;
    const DATA_FRESHNESS_MS = 10_000; // UI data-age threshold only; not a clinical threshold.
    const freshness = document.getElementById("data-freshness");
    let latestReadingTimestamp = null;
    let freshnessTimer = null;

    function updateFreshnessIndicator() {
        const timestamp = latestReadingTimestamp === null ? null : Date.parse(latestReadingTimestamp);
        const kind = timestamp === null ? "no-data" : !Number.isFinite(timestamp) ? "unknown" :
            Math.max(0, Date.now() - timestamp) <= DATA_FRESHNESS_MS ? "fresh" : "stale";
        const label = {"no-data": "No data yet", unknown: "Unknown", fresh: "Fresh data", stale: "Stale data"}[kind];
        if (freshness.textContent !== label) freshness.textContent = label;
        freshness.dataset.state = kind;
    }

    function onVisibilityChange() {
        if (!document.hidden) updateFreshnessIndicator();
    }
    const chartState = document.getElementById("chart-state");
    const metrics = [["heart_rate", "bpm"], ["spo2", "%"], ["temperature_c", "°C"]];
    const charts = metrics.map(([key, unit]) => new Chart(document.getElementById(`chart-${key}`), {
        type: "line",
        data: {datasets: [{label: unit, data: [], borderColor: "#16848b", backgroundColor: "#16848b",
            borderWidth: 2, pointRadius: 2, pointHoverRadius: 4, tension: 0}]},
        options: {
            responsive: true, maintainAspectRatio: false, animation: false,
            plugins: {legend: {display: false}, tooltip: {callbacks: {
                title: items => items.length ? new Date(items[0].raw.recorded_at).toLocaleString() : "",
                label: item => `${item.parsed.y} ${unit}`
            }}},
            scales: {
                x: {type: "linear", title: {display: true, text: "Measurement time"},
                    ticks: {maxTicksLimit: 4, maxRotation: 0,
                        callback: value => new Date(value).toLocaleTimeString()}, grid: {display: false}},
                y: {title: {display: true, text: unit}, ticks: {maxTicksLimit: 5}, grid: {color: "#edf2f4"}}
            }
        }
    }));
    let chartReadings = [];
    let selectedId = null;
    let socket = null;
    let retryTimer = null;
    let refreshController = null;
    let retries = 0;
    let stopped = false;

    const alertList = document.getElementById("alert-list");
    const alertState = document.getElementById("alert-state");
    const alertCount = document.getElementById("alert-count");
    const MAX_DISPLAYED_ALERTS = 10;
    let alertController = null;
    let alertGeneration = 0;

    function cancelAlerts() {
        alertGeneration += 1;
        alertController?.abort();
        alertController = null;
    }

    function sectionState(element, kind, message) {
        element.dataset.state = kind;
        if (element.textContent !== message) element.textContent = message;
    }

    async function loadPatientAlerts(patientId, announce = false) {
        alertState.setAttribute("aria-live", announce ? "polite" : "off");
        alertList.replaceChildren();
        alertCount.textContent = "0";
        sectionState(alertState, "loading", "Loading alerts…");
        cancelAlerts();
        const generation = alertGeneration;
        const controller = new AbortController();
        alertController = controller;
        const current = () => generation === alertGeneration && selectedId === patientId && !stopped;
        try {
            const response = await fetch(`/api/patients/${patientId}/alerts`, {
                signal: controller.signal, cache: "no-store", credentials: "same-origin"
            });
            if (!current()) return;
            if (!response.ok || response.redirected) throw new Error("Alerts unavailable");
            const alerts = await response.json();
            if (!current()) return;
            if (!Array.isArray(alerts) || alerts.length > 50 || !alerts.every(alert =>
                alert.patient_id === patientId && Number.isSafeInteger(alert.id) &&
                typeof alert.message === "string" && typeof alert.severity === "string" &&
                typeof alert.is_resolved === "boolean" && typeof alert.created_at === "string" &&
                Number.isFinite(Date.parse(alert.created_at)))) throw new Error("Invalid alerts");
            alertList.replaceChildren();
            const displayed = alerts.slice(0, MAX_DISPLAYED_ALERTS);
            for (const alert of displayed) {
                const item = document.createElement("li");
                item.className = alert.severity === "warning" ? "alert-item alert-warning" : "alert-item";
                const message = document.createElement("p");
                message.textContent = alert.message;
                const details = document.createElement("div");
                details.className = "alert-details";
                const severity = document.createElement("span");
                severity.textContent = alert.severity === "warning" ? "Warning" : alert.severity;
                const time = document.createElement("time");
                time.dateTime = alert.created_at;
                time.textContent = new Date(alert.created_at).toLocaleString();
                const resolution = document.createElement("span");
                resolution.textContent = alert.is_resolved ? "Resolved" : "Open";
                details.append(severity, time, resolution);
                item.append(message, details);
                alertList.append(item);
            }
            alertCount.textContent = String(displayed.length);
            buttons.find(button => Number(button.dataset.patientId) === patientId)
                .querySelector(".overview-alert-count").textContent = String(displayed.length);
            sectionState(alertState, displayed.length ? "data" : "empty", displayed.length ? `Showing latest ${displayed.length} demo alerts` :
                "No demo threshold alerts for this patient.");
        } catch (error) {
            if (error.name !== "AbortError" && current()) {
                alertList.replaceChildren();
                alertCount.textContent = "0";
                sectionState(alertState, "error", "Unable to load demo alerts.");
            }
        }
    }

    const fuzzyState = document.getElementById("fuzzy-state");
    const fuzzyContent = document.getElementById("fuzzy-content");
    let fuzzyController = null;
    let fuzzyGeneration = 0;
    const fuzzyGroups = {heart_rate: ["low", "normal", "high"], spo2: ["low", "normal"], temperature: ["low", "normal", "high"]};
    const fuzzyLabels = {normal: "Normal", warning: "Warning", critical: "Critical demo status", low: "Low", high: "High"};

    function cancelFuzzy() {
        fuzzyGeneration += 1;
        fuzzyController?.abort();
        fuzzyController = null;
    }

    function membershipBars(container, values, keys, group) {
        container.replaceChildren();
        for (const key of keys) {
            const row = document.createElement("div");
            row.className = "fuzzy-member";
            const label = document.createElement("span");
            label.textContent = fuzzyLabels[key];
            const bar = document.createElement("progress");
            bar.max = 1;
            bar.value = values[key];
            bar.setAttribute("aria-label", `${group}: ${fuzzyLabels[key]} membership`);
            const percentage = document.createElement("span");
            percentage.textContent = `${Math.round(values[key] * 100)}%`;
            row.append(label, bar, percentage);
            container.append(row);
        }
    }

    async function loadFuzzy(patientId, announce = false) {
        cancelFuzzy();
        const generation = fuzzyGeneration;
        const controller = new AbortController();
        fuzzyController = controller;
        const current = () => generation === fuzzyGeneration && selectedId === patientId && !stopped;
        fuzzyContent.hidden = true;
        delete fuzzyContent.dataset.readingId;
        document.getElementById("fuzzy-score").textContent = "";
        document.getElementById("fuzzy-status").textContent = "";
        document.getElementById("fuzzy-time").textContent = "";
        document.getElementById("fuzzy-time").removeAttribute("datetime");
        document.getElementById("fuzzy-outputs").replaceChildren();
        document.getElementById("fuzzy-inputs").replaceChildren();
        fuzzyState.setAttribute("aria-live", announce ? "polite" : "off");
        sectionState(fuzzyState, "loading", "Calculating fuzzy assessment...");
        try {
            const response = await fetch(`/api/patients/${patientId}/fuzzy-assessment`, {
                signal: controller.signal, cache: "no-store", credentials: "same-origin"
            });
            if (!current()) return;
            if (!response.ok || response.redirected) throw new Error("Assessment unavailable");
            const data = await response.json();
            if (!current()) return;
            if (!data || data.patient_id !== patientId) throw new Error("Invalid assessment");
            if (data.reading_id === null && data.assessment === null && data.recorded_at === null) {
                sectionState(fuzzyState, "empty", "No fuzzy assessment available yet. A sensor reading is required before an assessment can be calculated.");
                return;
            }
            const a = data.assessment;
            const validDegrees = (v, keys) => v && keys.every(k => Number.isFinite(v[k]) && v[k] >= 0 && v[k] <= 1);
            if (!Number.isSafeInteger(data.reading_id) || data.reading_id <= 0 || typeof data.recorded_at !== "string" ||
                !Number.isFinite(Date.parse(data.recorded_at)) || !a || !["normal", "warning", "critical"].includes(a.status) ||
                !Number.isFinite(a.risk_score) || a.risk_score < 0 || a.risk_score > 100 ||
                !validDegrees(a.output_memberships, ["normal", "warning", "critical"]) ||
                !Object.entries(fuzzyGroups).every(([key, values]) => validDegrees(a.input_memberships?.[key], values))) throw new Error("Invalid assessment");
            document.getElementById("fuzzy-status").textContent = fuzzyLabels[a.status];
            document.getElementById("fuzzy-score").textContent = a.risk_score.toFixed(1);
            const time = document.getElementById("fuzzy-time");
            time.dateTime = data.recorded_at;
            time.textContent = new Date(data.recorded_at).toLocaleString();
            membershipBars(document.getElementById("fuzzy-outputs"), a.output_memberships, ["normal", "warning", "critical"], "Output");
            const names = {heart_rate: "Heart Rate", spo2: "SpO₂", temperature: "Temperature"};
            for (const [key, keys] of Object.entries(fuzzyGroups)) {
                const group = document.createElement("div");
                const heading = document.createElement("h3");
                heading.textContent = names[key];
                const bars = document.createElement("div");
                bars.className = "fuzzy-bars";
                membershipBars(bars, a.input_memberships[key], keys, names[key]);
                group.append(heading, bars);
                document.getElementById("fuzzy-inputs").append(group);
            }
            fuzzyContent.dataset.readingId = String(data.reading_id);
            fuzzyContent.hidden = false;
            sectionState(fuzzyState, "data", "");
        } catch (error) {
            if (error.name !== "AbortError" && current()) sectionState(fuzzyState, "error", "Unable to load fuzzy assessment.");
        }
    }

    const historyBody = document.getElementById("history-body");
    const historyState = document.getElementById("history-state");
    let historyReadings = [];
    let historyController = null;
    let historyGeneration = 0;

    function cancelHistory() {
        historyGeneration += 1;
        historyController?.abort();
        historyController = null;
    }

    function updateHistory(readings) {
        // Merge snapshots and live readings so a slow snapshot cannot erase a new event.
        const unique = new Map([...historyReadings, ...readings].filter(validReading).map(r => [r.id, r]));
        historyReadings = [...unique.values()].sort((a, b) => compareReadings(b, a)).slice(0, MAX_RECENT_READINGS);
        historyBody.replaceChildren();
        for (const reading of historyReadings) {
            const row = document.createElement("tr");
            row.dataset.readingId = String(reading.id);
            const timeCell = document.createElement("td");
            const time = document.createElement("time");
            time.dateTime = reading.recorded_at;
            time.textContent = new Date(reading.recorded_at).toLocaleString();
            timeCell.append(time);
            row.append(timeCell);
            for (const value of [`${reading.heart_rate} bpm`, `${Number(reading.spo2.toFixed(1))}%`, `${reading.temperature_c.toFixed(1)} °C`]) {
                const cell = document.createElement("td");
                cell.textContent = value;
                row.append(cell);
            }
            historyBody.append(row);
        }
        sectionState(historyState, historyReadings.length ? "data" : "empty", historyReadings.length ? `Showing latest ${historyReadings.length} readings` :
            "No readings available for this patient yet.");
    }

    async function loadReadingHistory(patientId, announce = false) {
        historyState.setAttribute("aria-live", announce ? "polite" : "off");
        historyBody.replaceChildren();
        sectionState(historyState, "loading", "Loading recent readings…");
        cancelHistory();
        const generation = historyGeneration;
        const controller = new AbortController();
        historyController = controller;
        const current = () => generation === historyGeneration && selectedId === patientId && !stopped;
        try {
            const response = await fetch(`/api/patients/${patientId}/readings?limit=${MAX_RECENT_READINGS}`, {
                signal: controller.signal, cache: "no-store", credentials: "same-origin"
            });
            if (!current()) return;
            if (!response.ok || response.redirected) throw new Error("History unavailable");
            const readings = await response.json();
            if (!current()) return;
            if (!Array.isArray(readings) || readings.length > MAX_RECENT_READINGS || !readings.every(validReading)) {
                throw new Error("Invalid history");
            }
            updateHistory(readings);
        } catch (error) {
            if (error.name !== "AbortError" && current()) {
                historyBody.replaceChildren();
                sectionState(historyState, "error", "Unable to load recent readings.");
            }
        }
    }

    function validReading(reading) {
        return reading && Number.isSafeInteger(reading.id) && reading.id > 0 &&
            reading.patient_id === selectedId && Number.isInteger(reading.heart_rate) &&
            reading.heart_rate > 0 && reading.heart_rate <= 300 &&
            Number.isFinite(reading.spo2) && reading.spo2 >= 0 && reading.spo2 <= 100 &&
            Number.isFinite(reading.temperature_c) && reading.temperature_c >= 20 &&
            reading.temperature_c <= 50 && typeof reading.recorded_at === "string" &&
            Number.isFinite(Date.parse(reading.recorded_at));
    }

    function updateConnectionStatus(label) {
        if (status.textContent !== label) status.textContent = label;
        status.dataset.state = label.replace("…", "").toLowerCase();
    }

    function updateOverview(patientId, reading) {
        const button = buttons.find(button => Number(button.dataset.patientId) === patientId);
        button.querySelector(".overview-vitals").textContent = reading ?
            `HR ${reading.heart_rate} bpm · SpO₂ ${Number(reading.spo2.toFixed(1))}% · Temp ${reading.temperature_c.toFixed(1)} °C` : "No readings yet";
        const time = button.querySelector("time");
        time.textContent = reading ? new Date(reading.recorded_at).toLocaleString() : "No readings yet";
        if (reading) time.dateTime = reading.recorded_at;
        else time.removeAttribute("datetime");
    }

    function updateVitalCards(reading) {
        latestReadingTimestamp = reading ? reading.recorded_at : null;
        updateFreshnessIndicator();
        updateOverview(selectedId, reading);
        document.getElementById("heart-rate").textContent = reading ? reading.heart_rate : "—";
        document.getElementById("spo2").textContent = reading ? Number(reading.spo2.toFixed(1)) : "—";
        document.getElementById("temperature").textContent = reading ? reading.temperature_c.toFixed(1) : "—";
        const time = document.getElementById("last-updated");
        time.textContent = reading ? new Date(reading.recorded_at).toLocaleString([], {
            year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit"
        }) : "No readings received yet";
        if (reading) time.dateTime = reading.recorded_at;
        else time.removeAttribute("datetime");
        state.textContent = reading ? "" : "No readings available for this patient yet.";
    }

    function compareReadings(a, b) {
        // Date.parse retains milliseconds; SQLite timestamps can also contain microseconds.
        const fraction = reading => Number((reading.recorded_at.match(/\.(\d+)/)?.[1] || "0").padEnd(6, "0"));
        return Date.parse(a.recorded_at) - Date.parse(b.recorded_at) || fraction(a) - fraction(b) || a.id - b.id;
    }

    function updateCharts(readings) {
        // Merge live events with snapshots: bounded, deduplicated and chronological.
        const unique = new Map([...chartReadings, ...readings].filter(validReading).map(reading => [reading.id, reading]));
        chartReadings = [...unique.values()].sort(compareReadings).slice(-MAX_RECENT_READINGS);
        charts.forEach((chart, index) => {
            chart.data.datasets[0].data = chartReadings.map(reading => ({
                x: Date.parse(reading.recorded_at), y: reading[metrics[index][0]],
                id: reading.id, patient_id: reading.patient_id, recorded_at: reading.recorded_at
            }));
            const first = chartReadings[0];
            const last = chartReadings.at(-1);
            const start = first ? Date.parse(first.recorded_at) : undefined;
            const end = last ? Date.parse(last.recorded_at) : undefined;
            // Explicit bounds avoid numeric-axis rounding across hours for a short window.
            chart.options.scales.x.min = first ? start - (start === end ? 1000 : 0) : undefined;
            chart.options.scales.x.max = last ? end + (start === end ? 1000 : 0) : undefined;
            chart.update("none");
        });
        chartState.textContent = chartReadings.length ? "" :
            "No readings available yet. Start the sensor simulator to begin monitoring.";
    }

    function acceptReading(reading) {
        if (!validReading(reading)) return;
        updateCharts([reading]);
        const patient = byId.get(selectedId);
        const previous = patient.reading;
        // A delayed refresh/event must not replace a chronologically newer reading.
        if (previous && compareReadings(previous, reading) > 0) return;
        patient.reading = reading;
        updateVitalCards(reading);
    }

    async function refreshRecent(connection, patientId) {
        refreshController?.abort();
        const controller = new AbortController();
        refreshController = controller;
        try {
            const response = await fetch(`/api/patients/${patientId}/readings/recent`, {
                signal: controller.signal, cache: "no-store", credentials: "same-origin"
            });
            if (socket !== connection || stopped) return;
            if (response.redirected || [401, 403, 404].includes(response.status)) {
                stop();
                state.textContent = "Access unavailable. Sign in again to continue monitoring.";
                return;
            }
            if (!response.ok) throw new Error("Refresh failed");
            const readings = await response.json();
            if (socket !== connection || stopped) return;
            if (!Array.isArray(readings) || readings.length > MAX_RECENT_READINGS || !readings.every(validReading)) {
                throw new Error("Invalid readings");
            }
            updateCharts(readings);
            const latest = chartReadings.at(-1);
            if (latest) {
                byId.get(patientId).reading = latest;
                updateVitalCards(latest);
            } else updateVitalCards(byId.get(patientId).reading);
        } catch (error) {
            if (error.name !== "AbortError" && socket === connection && !stopped) {
                state.textContent = "Unable to refresh saved readings. Reconnecting…";
                chartState.textContent = "Unable to load recent readings. Reconnecting…";
                connection.close();
            }
        }
    }

    function disconnectWebSocket() {
        clearTimeout(retryTimer);
        retryTimer = null;
        refreshController?.abort();
        refreshController = null;
        const previous = socket;
        socket = null; // Invalidates every callback from the previous subscription.
        if (previous) previous.close();
    }

    function connectWebSocket(patientId) {
        if (stopped || selectedId !== patientId) return;
        updateConnectionStatus(retries ? "Reconnecting…" : "Connecting…");
        const protocol = location.protocol === "https:" ? "wss:" : "ws:";
        const connection = new WebSocket(`${protocol}//${location.host}/ws/patients/${patientId}`);
        socket = connection;
        connection.onopen = () => {
            if (socket === connection && !stopped) updateConnectionStatus("Connected");
        };
        connection.onmessage = event => {
            if (socket !== connection || selectedId !== patientId || stopped) return;
            let message;
            try { message = JSON.parse(event.data); } catch { return; }
            if (!message || typeof message !== "object") return;
            if (message.type === "connected" && message.patient_id === patientId) {
                // Subscribe first, then recover anything missed while disconnected.
                refreshRecent(connection, patientId);
                loadReadingHistory(patientId);
                loadPatientAlerts(patientId);
                loadFuzzy(patientId);
            } else if (message.type === "reading" && validReading(message.data)) {
                acceptReading(message.data);
                updateHistory([message.data]);
                loadPatientAlerts(patientId);
                loadFuzzy(patientId);
            }
        };
        connection.onerror = () => { if (socket === connection) connection.close(); };
        connection.onclose = event => {
            if (socket !== connection || stopped) return;
            socket = null;
            refreshController?.abort();
            updateConnectionStatus("Disconnected");
            if (event.code === 1008 || retries >= 5) {
                state.textContent = "Live updates stopped. Reload the page to reconnect or sign in again.";
                return;
            }
            const delay = Math.min(1000 * 2 ** retries, 15000);
            retries += 1;
            updateConnectionStatus("Reconnecting…");
            retryTimer = setTimeout(() => connectWebSocket(patientId), delay);
        };
    }

    function selectPatient(patientId) {
        if (!byId.has(patientId) || stopped) return;
        disconnectWebSocket();
        selectedId = patientId;
        loadFuzzy(patientId, true);
        historyReadings = [];
        historyBody.replaceChildren();
        historyState.textContent = "Loading recent readings…";
        loadReadingHistory(patientId, true);
        alertList.replaceChildren();
        alertCount.textContent = "0";
        alertState.textContent = "Loading alerts…";
        loadPatientAlerts(patientId, true);
        chartReadings = [];
        updateCharts([]);
        chartState.textContent = "Loading recent readings…";
        retries = 0;
        const patient = byId.get(patientId);
        buttons.forEach(button => {
            const selected = Number(button.dataset.patientId) === patientId;
            button.setAttribute("aria-pressed", String(selected));
            button.querySelector(".overview-selected").textContent = selected ? "Monitoring" : "Monitor Patient";
        });
        document.getElementById("patient-name").textContent = patient.name;
        document.getElementById("patient-detail").textContent = `Patient #${patient.id} · ${patient.age} years · ${patient.gender}`;
        updateVitalCards(patient.reading);
        state.textContent = "Loading latest saved reading…";
        connectWebSocket(patientId);
    }

    function onSelect(event) { selectPatient(Number(event.currentTarget.dataset.patientId)); }
    function stop() {
        stopped = true;
        cancelFuzzy();
        clearInterval(freshnessTimer);
        freshnessTimer = null;
        document.removeEventListener("visibilitychange", onVisibilityChange);
        cancelAlerts();
        cancelHistory();
        disconnectWebSocket();
        updateConnectionStatus("Disconnected");
        buttons.forEach(button => button.removeEventListener("click", onSelect));
        charts.forEach(chart => chart.destroy());
    }
    buttons.forEach(button => button.addEventListener("click", onSelect));
    document.getElementById("logout-form").addEventListener("submit", stop, {once: true});
    window.addEventListener("pagehide", stop, {once: true});
    window.addEventListener("pageshow", event => { if (event.persisted) location.reload(); });
    patients.forEach(patient => updateOverview(patient.id, patient.reading));
    selectPatient(patients[0].id);
    freshnessTimer = setInterval(updateFreshnessIndicator, 1000);
    document.addEventListener("visibilitychange", onVisibilityChange);
})();
