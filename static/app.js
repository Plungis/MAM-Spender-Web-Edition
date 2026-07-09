let state = null;
let settingsDirty = false;
let chartMode = "pie";
let bonusHistoryPage = 1;

const $ = (id) => document.getElementById(id);
const fmt = new Intl.NumberFormat();
const settingIds = ["buyVip", "buyUploadCredit", "flOnly", "alternateFlUpload", "themeName", "pointsBuffer", "delayMinutes", "serverPort", "cookiePath"];
const maxPointsBuffer = 49000;
const minServerPort = 1024;
const maxServerPort = 65535;
const categoryLabels = {
  upload_credit: "Upload Credit",
  freeleech_wedge: "Freeleech Wedge",
  vip: "VIP Renewal"
};
const pointsPerPurchase = 50000;

function formatCountdown(seconds) {
  if (seconds === null || seconds === undefined) return "Not scheduled";
  const s = Math.max(0, Number(seconds));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = s % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

function formatDelayLabel(minutes) {
  const total = Math.max(0, Number(minutes || 0));
  const hours = Math.floor(total / 60);
  const mins = total % 60;
  if (hours > 0 && mins > 0) return `${hours}h ${mins}m`;
  if (hours > 0) return `${hours}h`;
  return `${mins}m`;
}

function formatCompactNumber(value) {
  if (value >= 1000000) return `${(value / 1000000).toFixed(value >= 10000000 ? 0 : 1)}M`;
  if (value >= 1000) return `${Math.round(value / 1000)}k`;
  return String(Math.round(value));
}

function formatDate(value) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit"
  });
}

function formatUtcDate(value) {
  if (!value) return "N/A";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], {
    timeZone: "UTC",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short"
  });
}

function formatDualTime(value) {
  if (!value) return "N/A";
  return `<span class="time-stack"><span>${escapeHtml(formatDate(value))}</span><small>MAM UTC: ${escapeHtml(formatUtcDate(value))}</small></span>`;
}

function nextUtcWeekday(day, hour = 0, minute = 0) {
  const now = new Date();
  const next = new Date(now);
  next.setUTCSeconds(0, 0);
  next.setUTCMinutes(minute);
  next.setUTCHours(hour);
  const daysAhead = (day - next.getUTCDay() + 7) % 7;
  next.setUTCDate(next.getUTCDate() + daysAhead);
  if (next <= now) next.setUTCDate(next.getUTCDate() + 7);
  return next;
}

function nextUtcDayStart() {
  const now = new Date();
  return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate() + 1, 0, 0, 0));
}

function formatCountdownTo(date) {
  const seconds = Math.max(0, Math.floor((date.getTime() - Date.now()) / 1000));
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h ${minutes}m`;
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

function renderMarquee() {
  const local = new Date();
  const vaultReset = nextUtcDayStart();
  const lottoReset = nextUtcWeekday(1, 0, 0);
  const lottoDrawing = nextUtcWeekday(1, 9, 0);
  const pieces = [
    `Local Time: ${local.toLocaleString()}`,
    `MAM Server Time (UTC): ${local.toLocaleString([], { timeZone: "UTC", timeZoneName: "short" })}`,
    `Vault donation reset: ${formatCountdownTo(vaultReset)} (${formatUtcDate(vaultReset.toISOString())})`,
    `Lotto reset: ${formatCountdownTo(lottoReset)} (${formatUtcDate(lottoReset.toISOString())})`,
    `Lotto drawing: ${formatCountdownTo(lottoDrawing)} (${formatUtcDate(lottoDrawing.toISOString())})`
  ];
  $("infoMarquee").textContent = `${pieces.join("  |  ")}  |  ${pieces.join("  |  ")}`;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function cssVar(name, fallback) {
  const value = getComputedStyle(document.body).getPropertyValue(name).trim();
  return value || fallback;
}

function themedRgba(rgbVar, alpha) {
  return `rgba(${cssVar(rgbVar, "57, 255, 102")}, ${alpha})`;
}

function categoryColor(category) {
  if (document.body.dataset.theme === "mouse") {
    if (category === "upload_credit") return "#ff6fb8";
    if (category === "freeleech_wedge") return "#f7d75f";
    if (category === "vip") return "#66d9ff";
    return "#d7d0d8";
  }
  if (category === "upload_credit") return cssVar("--accent", "#82ff7e");
  if (category === "freeleech_wedge") return cssVar("--warning", "#d6ff6b");
  if (category === "vip") return cssVar("--line", "#7ee7ff");
  return cssVar("--text", "#9cff9c");
}

function renderHistory() {
  const rows = $("historyRows");
  const history = state.history || [];
  if (!history.length) {
    rows.innerHTML = '<tr><td colspan="6">No history yet.</td></tr>';
    return;
  }
  rows.innerHTML = history.map((entry) => {
    const points = entry.points_spent ? fmt.format(entry.points_spent) : "0";
    const upload = entry.upload_gb ? `${fmt.format(entry.upload_gb)} GiB` : "-";
    const wedges = entry.freeleech_wedges ? fmt.format(entry.freeleech_wedges) : "-";
    const vip = entry.vip_purchased ? "Yes" : "-";
    return `<tr>
      <td>${formatDualTime(entry.started_at || entry.created_at)}</td>
      <td>${escapeHtml(entry.result || entry.kind || "N/A")}</td>
      <td>${points}</td>
      <td>${upload}</td>
      <td>${wedges}</td>
      <td>${vip}</td>
    </tr>`;
  }).join("");
}

function renderSpendRows() {
  const rows = $("spendRows");
  const events = [...(state.spend_events || [])].reverse();
  if (!events.length) {
    rows.innerHTML = '<tr><td colspan="5">No spending events yet.</td></tr>';
    return;
  }
  rows.innerHTML = events.map((event) => {
    const units = event.units ? `${fmt.format(event.units)} ${escapeHtml(event.unit_label || "")}` : "-";
    const balance = event.balance_after === null || event.balance_after === undefined
      ? "-"
      : fmt.format(event.balance_after);
    return `<tr>
      <td>${formatDualTime(event.created_at)}</td>
      <td>${escapeHtml(event.label || event.category)}</td>
      <td>${fmt.format(event.points_spent || 0)}</td>
      <td>${units}</td>
      <td>${balance}</td>
    </tr>`;
  }).join("");
}

function renderMamUserData() {
  const data = state.mam_user_data || {};
  $("mamDataUsername").textContent = data.username || "N/A";
  $("mamDataClass").textContent = data.class || "N/A";
  $("mamDataUploaded").textContent = data.uploaded || "N/A";
  $("mamDataDownloaded").textContent = data.downloaded || "N/A";
  $("mamDataRatio").textContent = data.ratio || "N/A";
  $("mamDataBonus").textContent = data.bonus || "N/A";
  $("mamDataWedges").textContent = data.fl_wedges || "N/A";
  $("mamDataInvites").textContent = data.invites || "N/A";
  $("mamDataUnsats").textContent = data.unsats || "N/A";
  $("mamDataPph").textContent = data.points_per_hour || "N/A";
  $("mamDataClient").textContent = data.client_status || "N/A";

  if (state.mam_user_error) {
    $("mamDataStatus").textContent = `MAM user data error: ${state.mam_user_error}`;
  } else if (state.mam_user_fetched_at) {
    $("mamDataStatus").innerHTML = `Last loaded: ${formatDualTime(state.mam_user_fetched_at)}`;
  } else {
    $("mamDataStatus").textContent = "Load user data to pull the latest MAM account snapshot.";
  }

  const notifications = data.notifications || [];
  $("mamNotifications").innerHTML = notifications.length
    ? notifications.map((item) => `<p>${escapeHtml(item)}</p>`).join("")
    : "";
}

function renderBonusHistory() {
  const rows = $("bonusHistoryRows");
  const history = state.bonus_history || [];
  const pageSize = Number($("bonusHistoryPageSize").value || 10);
  const totalPages = Math.max(1, Math.ceil(history.length / pageSize));
  bonusHistoryPage = Math.max(1, Math.min(totalPages, bonusHistoryPage));
  if (state.bonus_history_error) {
    $("bonusHistoryStatus").textContent = `Bonus history error: ${state.bonus_history_error}`;
  } else if (state.bonus_history_fetched_at) {
    $("bonusHistoryStatus").innerHTML =
      `Last loaded: ${formatDualTime(state.bonus_history_fetched_at)}. ${fmt.format(history.length)} entries available locally.`;
  } else {
    $("bonusHistoryStatus").textContent = "Load bonus history to pull up to 500 returned point and wedge entries from MAM.";
  }
  if (!history.length) {
    rows.innerHTML = '<tr><td colspan="5">No bonus history loaded yet.</td></tr>';
    $("bonusHistoryPageStatus").textContent = "Page 0 of 0";
    $("bonusHistoryPrevBtn").disabled = true;
    $("bonusHistoryNextBtn").disabled = true;
    return;
  }
  const start = (bonusHistoryPage - 1) * pageSize;
  const pageRows = history.slice(start, start + pageSize);
  rows.innerHTML = pageRows.map((entry) => {
    const amountNumber = Number(entry.amount);
    const amount = Number.isFinite(amountNumber) ? fmt.format(amountNumber) : "-";
    const other = entry.other_name && entry.other_name !== "N/A"
      ? entry.other_name
      : entry.other_userid || "-";
    return `<tr>
      <td>${formatDualTime(entry.timestamp)}</td>
      <td>${escapeHtml(entry.type || "N/A")}</td>
      <td>${amount}</td>
      <td>${escapeHtml(entry.title || "N/A")}</td>
      <td>${escapeHtml(other)}</td>
    </tr>`;
  }).join("");
  $("bonusHistoryPageStatus").textContent =
    `Showing ${fmt.format(start + 1)}-${fmt.format(start + pageRows.length)} of ${fmt.format(history.length)} | Page ${bonusHistoryPage} of ${totalPages}`;
  $("bonusHistoryPrevBtn").disabled = bonusHistoryPage <= 1;
  $("bonusHistoryNextBtn").disabled = bonusHistoryPage >= totalPages;
}

function spendSlices() {
  const totals = {};
  (state.spend_events || []).forEach((event) => {
    const category = event.category || "other";
    totals[category] = (totals[category] || 0) + Number(event.points_spent || 0);
  });
  return Object.entries(totals)
    .filter(([, points]) => points > 0)
    .sort((a, b) => b[1] - a[1]);
}

function prepareChart() {
  const canvas = $("spendChart");
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  const fontFamily = getComputedStyle(document.body).fontFamily;
  const surface = cssVar("--surface", "#020703");
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = surface;
  ctx.fillRect(0, 0, width, height);
  return { canvas, ctx, width, height, fontFamily, surface };
}

function drawNoChartMessage(ctx, fontFamily, message) {
  ctx.fillStyle = cssVar("--muted", "#5fbf6a");
  ctx.font = `16px ${fontFamily}`;
  ctx.fillText(message, 56, 70);
  $("graphLegend").innerHTML = "";
}

function renderChartLegend(slices, totalPoints) {
  $("graphLegend").innerHTML = slices.map(([category, points]) => {
    const label = categoryLabels[category] || category.replaceAll("_", " ");
    const percent = ((points / totalPoints) * 100).toFixed(points === totalPoints ? 0 : 1);
    return `<span><i style="background:${categoryColor(category)}"></i>${escapeHtml(label)}: ${fmt.format(points)} pts (${percent}%)</span>`;
  }).join("");
}

function drawSpendChart() {
  if (!state) return;
  const events = state.spend_events || [];
  const { ctx, width, height, fontFamily, surface } = prepareChart();
  $("chartTitle").textContent = chartMode === "bar"
    ? "Spending Bar Chart"
    : chartMode === "timeline"
      ? "Spending Timeline"
      : "Spending Pie Chart";
  if (!events.length) {
    drawNoChartMessage(ctx, fontFamily, "No spending events recorded yet.");
    return;
  }

  const slices = spendSlices();
  const totalPoints = slices.reduce((sum, [, points]) => sum + points, 0);

  if (!totalPoints) {
    drawNoChartMessage(ctx, fontFamily, "No point spending recorded yet.");
    return;
  }

  if (chartMode === "bar") {
    drawBarChart(ctx, width, height, fontFamily, slices, totalPoints);
    renderChartLegend(slices, totalPoints);
    return;
  }
  if (chartMode === "timeline") {
    drawTimelineChart(ctx, width, height, fontFamily, events);
    renderChartLegend(slices, totalPoints);
    return;
  }
  drawPieChart(ctx, width, height, fontFamily, surface, slices, totalPoints);
  renderChartLegend(slices, totalPoints);
}

function drawPieChart(ctx, width, height, fontFamily, surface, slices, totalPoints) {
  const centerX = Math.min(width * 0.36, 320);
  const centerY = height / 2;
  const radius = Math.min(height * 0.34, width * 0.24);
  let startAngle = -Math.PI / 2;

  ctx.save();
  ctx.shadowColor = themedRgba("--glow-rgb", 0.45);
  ctx.shadowBlur = 18;
  slices.forEach(([category, points]) => {
    const angle = (points / totalPoints) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(centerX, centerY);
    ctx.arc(centerX, centerY, radius, startAngle, startAngle + angle);
    ctx.closePath();
    ctx.fillStyle = categoryColor(category);
    ctx.fill();
    ctx.strokeStyle = surface;
    ctx.lineWidth = 3;
    ctx.stroke();
    startAngle += angle;
  });
  ctx.restore();

  ctx.beginPath();
  ctx.arc(centerX, centerY, radius * 0.46, 0, Math.PI * 2);
  ctx.fillStyle = surface;
  ctx.fill();
  ctx.strokeStyle = themedRgba("--glow-rgb", 0.48);
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.fillStyle = cssVar("--accent-strong", "#d9ffd8");
  ctx.font = `22px ${fontFamily}`;
  ctx.textAlign = "center";
  ctx.fillText(formatCompactNumber(totalPoints), centerX, centerY - 4);
  ctx.fillStyle = cssVar("--muted", "#5fbf6a");
  ctx.font = `12px ${fontFamily}`;
  ctx.fillText("points spent", centerX, centerY + 18);
  ctx.textAlign = "start";
}

function drawBarChart(ctx, width, height, fontFamily, slices, totalPoints) {
  const left = 72;
  const top = 38;
  const barHeight = 42;
  const gap = 22;
  const maxPoints = Math.max(...slices.map(([, points]) => points), 1);
  ctx.font = `14px ${fontFamily}`;
  slices.forEach(([category, points], index) => {
    const y = top + index * (barHeight + gap);
    const label = categoryLabels[category] || category.replaceAll("_", " ");
    const barWidth = Math.max(8, ((width - left - 180) * points) / maxPoints);
    ctx.fillStyle = categoryColor(category);
    ctx.shadowColor = themedRgba("--glow-rgb", 0.3);
    ctx.shadowBlur = 12;
    ctx.fillRect(left, y, barWidth, barHeight);
    ctx.shadowBlur = 0;
    ctx.strokeStyle = themedRgba("--glow-rgb", 0.35);
    ctx.strokeRect(left, y, width - left - 120, barHeight);
    ctx.fillStyle = cssVar("--accent-strong", "#d9ffd8");
    ctx.fillText(label, left, y - 8);
    ctx.fillStyle = cssVar("--muted", "#5fbf6a");
    ctx.fillText(`${fmt.format(points)} pts (${((points / totalPoints) * 100).toFixed(1)}%)`, left + barWidth + 14, y + 27);
  });
}

function drawTimelineChart(ctx, width, height, fontFamily, events) {
  const ordered = [...events]
    .filter((event) => Number(event.points_spent || 0) > 0)
    .sort((a, b) => new Date(a.created_at) - new Date(b.created_at));
  if (!ordered.length) {
    drawNoChartMessage(ctx, fontFamily, "No point spending recorded yet.");
    return;
  }
  let cumulative = 0;
  const points = ordered.map((event) => {
    cumulative += Number(event.points_spent || 0);
    return { date: new Date(event.created_at), value: cumulative, category: event.category || "other" };
  });
  const left = 64;
  const right = width - 42;
  const top = 36;
  const bottom = height - 54;
  const maxValue = Math.max(...points.map((point) => point.value), 1);
  ctx.strokeStyle = themedRgba("--glow-rgb", 0.35);
  ctx.lineWidth = 1;
  ctx.strokeRect(left, top, right - left, bottom - top);
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = left + (points.length === 1 ? 0.5 : index / (points.length - 1)) * (right - left);
    const y = bottom - (point.value / maxValue) * (bottom - top);
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.strokeStyle = cssVar("--accent", "#82ff7e");
  ctx.lineWidth = 3;
  ctx.shadowColor = themedRgba("--glow-rgb", 0.35);
  ctx.shadowBlur = 12;
  ctx.stroke();
  ctx.shadowBlur = 0;
  points.forEach((point, index) => {
    const x = left + (points.length === 1 ? 0.5 : index / (points.length - 1)) * (right - left);
    const y = bottom - (point.value / maxValue) * (bottom - top);
    ctx.fillStyle = categoryColor(point.category);
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fill();
  });
  ctx.fillStyle = cssVar("--accent-strong", "#d9ffd8");
  ctx.font = `13px ${fontFamily}`;
  ctx.fillText(`${fmt.format(maxValue)} cumulative pts`, left, top - 12);
  ctx.fillStyle = cssVar("--muted", "#5fbf6a");
  ctx.fillText(formatDate(points[0].date.toISOString()), left, bottom + 28);
  ctx.textAlign = "right";
  ctx.fillText(formatDate(points[points.length - 1].date.toISOString()), right, bottom + 28);
  ctx.textAlign = "start";
}

function settingsAreBeingEdited() {
  return settingsDirty || settingIds.includes(document.activeElement?.id);
}

function applyTheme(theme) {
  document.body.dataset.theme = theme || "green";
  $("themeName").value = theme || "green";
  document.querySelectorAll(".theme-option").forEach((button) => {
    button.classList.toggle("active", button.dataset.themeValue === $("themeName").value);
  });
}

function renderSettings() {
  if (settingsAreBeingEdited()) return;
  $("buyVip").checked = state.settings.buy_vip;
  $("buyUploadCredit").checked = state.settings.buy_upload_credit;
  $("flOnly").checked = state.settings.fl_only;
  $("alternateFlUpload").checked = state.settings.alternate_fl_upload;
  $("buyUploadCredit").disabled = state.settings.alternate_fl_upload;
  $("buyUploadCredit").closest(".toggle-line").classList.toggle("locked", state.settings.alternate_fl_upload);
  applyTheme(state.settings.theme || "green");
  $("pointsBuffer").value = state.settings.points_buffer;
  $("delayMinutes").value = state.settings.next_run_delay_minutes;
  $("serverPort").value = state.settings.server_port;
  $("cookiePath").value = state.settings.cookie_file_path;
}

function enforcePurchaseMode(changedId) {
  if (changedId === "flOnly" && $("flOnly").checked) {
    $("alternateFlUpload").checked = false;
    $("buyUploadCredit").checked = false;
  }
  if (changedId === "alternateFlUpload" && $("alternateFlUpload").checked) {
    $("flOnly").checked = false;
    $("buyUploadCredit").checked = true;
  }
  $("buyUploadCredit").disabled = $("alternateFlUpload").checked;
  $("buyUploadCredit").closest(".toggle-line").classList.toggle("locked", $("alternateFlUpload").checked);
  if (changedId === "buyUploadCredit" && $("alternateFlUpload").checked) {
    $("buyUploadCredit").checked = true;
  }
  if (changedId === "buyUploadCredit" && $("buyUploadCredit").checked) {
    $("flOnly").checked = false;
  }
}

function renderAlternateStatus() {
  const localAlternateOn = settingsAreBeingEdited()
    ? $("alternateFlUpload").checked
    : state.settings.alternate_fl_upload;
  const next = state.settings.alternate_next_purchase === "upload_credit"
    ? "Upload Credit"
    : "Freeleech Wedge";
  $("alternateStatus").textContent = localAlternateOn
    ? `Alternate mode target: ${next}.`
    : "Alternate mode is off.";
}

function renderPortStatus() {
  const activePort = state.active_port || state.constants?.default_server_port || 8765;
  const savedPort = settingsAreBeingEdited()
    ? clampNumber($("serverPort").value, minServerPort, maxServerPort)
    : state.settings.server_port;
  if (savedPort !== activePort) {
    $("portStatus").textContent =
      `Current server port: ${activePort}. Saved port ${savedPort} will be used after restart.`;
    return;
  }
  $("portStatus").textContent = `Current server port: ${activePort}.`;
}

function renderRunOverview() {
  const buffer = settingsAreBeingEdited()
    ? clampNumber($("pointsBuffer").value, 0, maxPointsBuffer)
    : state.settings.points_buffer;
  const delay = settingsAreBeingEdited()
    ? Math.max(2, Number($("delayMinutes").value || 15))
    : state.settings.next_run_delay_minutes;
  $("runOverview").textContent =
    `Current Settings: ${fmt.format(buffer)} buffer, runs every ${formatDelayLabel(delay)}`;
}

function renderReleaseStatus() {
  const release = state.release_status || {};
  $("appVersionLabel").textContent = release.current_label || state.app_version_label || "Web Edition V1.3.1 Beta 1";
  const status = $("releaseStatus");
  status.className = `release-status ${release.status || "checking"}`;
  const message = release.message || "Checking latest release...";
  if (release.latest_url && ["update_available", "current", "no_release"].includes(release.status)) {
    status.innerHTML = `<a href="${escapeHtml(release.latest_url)}" target="_blank" rel="noreferrer">${escapeHtml(message)}</a>`;
    return;
  }
  status.textContent = message;
}

function render(next) {
  state = next;
  const runningText = state.automation_running ? "Running now" : state.scheduler_enabled ? "Scheduled" : "Paused";
  $("statusLine").textContent = `Current Status: ${runningText}`;
  $("statusLine").classList.toggle("paused", runningText === "Paused");
  $("statusLine").classList.toggle("active", runningText !== "Paused");

  $("username").textContent = state.user.username;
  $("vipExpires").textContent = state.user.vip_expires;
  $("downloaded").textContent = state.user.downloaded;
  $("uploaded").textContent = state.user.uploaded;
  $("ratio").textContent = state.user.ratio;
  $("lastPoints").textContent = state.last_scan_points ? fmt.format(state.last_scan_points) : "N/A";
  $("pointsPerMin").textContent = state.points_per_min === null || state.points_per_min === undefined
    ? "N/A"
    : Number(state.points_per_min).toFixed(1);

  $("totalGb").textContent = fmt.format(state.totals.cumulative_upload_gb);
  $("totalPoints").textContent = fmt.format(state.totals.cumulative_points_spent);
  $("wedgeBought").textContent = fmt.format(state.totals.cumulative_freeleech_wedges || 0);
  $("wedgePoints").textContent = fmt.format(state.totals.cumulative_freeleech_points_spent || 0);
  $("vipPurchases").textContent = fmt.format(state.totals.cumulative_vip_purchases || 0);
  $("nextRun").textContent = state.scheduler_enabled ? formatCountdown(state.next_run_seconds) : "Not scheduled";

  renderMarquee();
  renderSettings();
  renderRunOverview();
  renderPortStatus();
  renderAlternateStatus();
  renderReleaseStatus();
  $("browseCookiePathBtn").disabled = !state.file_dialogs_enabled;
  $("browseCookiePathBtn").title = state.file_dialogs_enabled
    ? "Browse to a local Session_ID file"
    : "File picker is disabled in Docker. Use /app/data/filename or paste and save a Session_ID.";
  if (state.session_id_saved) {
    $("cookieStatus").textContent = "Mam Session_ID saved in local app settings as plain text.";
  } else if (state.cookie_exists) {
    $("cookieStatus").textContent = "Mam Session_ID file found. The app will read it when it runs.";
  } else if (!state.file_dialogs_enabled) {
    $("cookieStatus").textContent =
      `Docker mode: paste a Session_ID and save it, or put a file in data and use ${state.default_session_id_file || "/app/data/MAM.cookies"}.`;
  } else {
    $("cookieStatus").textContent = "No Mam Session_ID saved yet. Paste a Session_ID below or choose an existing file path.";
  }

  const logs = state.logs.join("\n");
  const box = $("logBox");
  if (box.textContent !== logs) {
    box.textContent = logs;
    box.scrollTop = box.scrollHeight;
  }

  renderHistory();
  renderMamUserData();
  renderBonusHistory();
  renderSpendRows();
  drawSpendChart();
}

async function api(path, body = null) {
  const options = body
    ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }
    : {};
  const response = await fetch(path, options);
  const text = await response.text();
  let payload = {};
  try {
    payload = text ? JSON.parse(text) : {};
  } catch (error) {
    const hint = text.trim().startsWith("<")
      ? "The app server returned a web page instead of app data. Close the command window, restart MAM Spender Web, then try again."
      : text.slice(0, 180);
    throw new Error(hint || "The app server returned an unreadable response.");
  }
  if (!response.ok || payload.error) throw new Error(payload.error || "Request failed.");
  render(payload);
  return payload;
}

async function saveSettings() {
  settingsDirty = false;
  return api("/api/settings", readSettings());
}

async function saveTheme(theme) {
  return api("/api/settings", { theme });
}

async function refresh() {
  try {
    const response = await fetch("/api/state");
    const text = await response.text();
    render(JSON.parse(text));
  } catch (error) {
    $("statusLine").textContent = error.message;
  }
}

function clampNumber(value, min, max) {
  const number = Number(value || 0);
  return Math.max(min, Math.min(max, number));
}

function readSettings() {
  return {
    buy_vip: $("buyVip").checked,
    buy_upload_credit: $("buyUploadCredit").checked,
    alternate_fl_upload: $("alternateFlUpload").checked,
    fl_only: $("flOnly").checked,
    theme: $("themeName").value,
    points_buffer: clampNumber($("pointsBuffer").value, 0, maxPointsBuffer),
    next_run_delay_minutes: Number($("delayMinutes").value || 15),
    server_port: clampNumber($("serverPort").value, minServerPort, maxServerPort),
    cookie_file_path: $("cookiePath").value
  };
}

function renderDelayEfficiency() {
  document.querySelectorAll("[data-pph-for]").forEach((item) => {
    const minutes = Number(item.dataset.pphFor || 0);
    const pointsPerHour = minutes > 0 ? pointsPerPurchase / (minutes / 60) : 0;
    item.textContent = `${formatCompactNumber(pointsPerHour)}/hr`;
    item.title = `${fmt.format(Math.round(pointsPerHour))} points per hour to refill one 50,000-point spend cycle`;
  });
}

document.querySelectorAll(".save-setting-btn").forEach((button) => {
  button.addEventListener("click", () => saveSettings().catch(alert));
});

document.querySelectorAll(".theme-option").forEach((button) => {
  button.addEventListener("click", async () => {
    const theme = button.dataset.themeValue;
    applyTheme(theme);
    if (state) drawSpendChart();
    try {
      await saveTheme(theme);
    } catch (error) {
      alert(error.message);
    }
  });
});

$("startBtn").addEventListener("click", async () => {
  try {
    await saveSettings();
    await api("/api/start", {});
  } catch (error) {
    alert(error.message);
  }
});
$("pauseBtn").addEventListener("click", () => api("/api/pause", {}).catch(alert));
$("runBtn").addEventListener("click", async () => {
  try {
    await saveSettings();
    await api("/api/run", {});
  } catch (error) {
    alert(error.message);
  }
});
$("resetBtn").addEventListener("click", () => {
  if (confirm("Reset cumulative totals?")) api("/api/reset_totals", {}).catch(alert);
});
$("refreshMamUserBtn").addEventListener("click", () => api("/api/refresh_mam_user", {}).catch(alert));
$("refreshBonusHistoryBtn").addEventListener("click", () => {
  bonusHistoryPage = 1;
  api("/api/refresh_bonus_history", {}).catch(alert);
});
$("bonusHistoryPageSize").addEventListener("change", () => {
  bonusHistoryPage = 1;
  if (state) renderBonusHistory();
});
$("bonusHistoryPrevBtn").addEventListener("click", () => {
  bonusHistoryPage = Math.max(1, bonusHistoryPage - 1);
  if (state) renderBonusHistory();
});
$("bonusHistoryNextBtn").addEventListener("click", () => {
  bonusHistoryPage += 1;
  if (state) renderBonusHistory();
});
$("browseCookiePathBtn").addEventListener("click", async () => {
  try {
    settingsDirty = false;
    await api("/api/browse_cookie_file", {});
  } catch (error) {
    alert(error.message);
  }
});
$("checkCookiePathBtn").addEventListener("click", async () => {
  try {
    await saveSettings();
    await api("/api/check_cookie_file", { cookie_file_path: $("cookiePath").value });
  } catch (error) {
    alert(error.message);
  }
});
$("saveCookieBtn").addEventListener("click", async () => {
  try {
    await saveSettings();
    const sessionId = $("cookieValue").value;
    if (!sessionId.trim()) {
      alert("Paste a Mam Session_ID first.");
      return;
    }
    const saveAsFile = confirm(
      state?.file_dialogs_enabled
        ? "Save this Mam Session_ID as a cookie file?\n\nOK: choose where to save the cookie file.\nCancel: store it locally in the app settings as plain text."
        : "Save this Mam Session_ID as /app/data/MAM.cookies?\n\nOK: save it as a mounted data file.\nCancel: store it locally in the app settings as plain text."
    );
    await api("/api/session_id", {
      session_id: sessionId,
      save_mode: saveAsFile ? "file" : "plain"
    });
    $("cookieValue").value = "";
  } catch (error) {
    alert(error.message);
  }
});

document.querySelectorAll(".tab").forEach((button) => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((tab) => tab.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.remove("active"));
    button.classList.add("active");
    $(button.dataset.tab).classList.add("active");
    if (state) drawSpendChart();
  });
});

document.querySelectorAll(".chart-mode").forEach((button) => {
  button.addEventListener("click", () => {
    chartMode = button.dataset.chartMode || "pie";
    document.querySelectorAll(".chart-mode").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
    if (state) drawSpendChart();
  });
});

settingIds.forEach((id) => {
  const element = $(id);
  element.addEventListener("input", () => {
    settingsDirty = true;
    enforcePurchaseMode(id);
    if (id === "pointsBuffer") {
      element.value = clampNumber(element.value, 0, maxPointsBuffer);
    }
    if (state) renderAlternateStatus();
    if (state) renderPortStatus();
    if (state) renderRunOverview();
  });
  element.addEventListener("change", () => {
    settingsDirty = true;
    enforcePurchaseMode(id);
    if (id === "pointsBuffer") {
      element.value = clampNumber(element.value, 0, maxPointsBuffer);
    }
    if (id === "serverPort") {
      element.value = clampNumber(element.value, minServerPort, maxServerPort);
    }
    if (state) renderAlternateStatus();
    if (state) renderPortStatus();
    if (state) renderRunOverview();
  });
});

document.querySelectorAll(".step-btn").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(button.dataset.target);
    const min = Number(input.min || 0);
    const max = input.max ? Number(input.max) : Number.POSITIVE_INFINITY;
    const step = Number(button.dataset.step || 0);
    input.value = Math.max(min, Math.min(max, Number(input.value || 0) + step));
    settingsDirty = true;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
});

document.querySelectorAll(".quick-btn").forEach((button) => {
  button.addEventListener("click", () => {
    const input = $(button.dataset.target);
    input.value = button.dataset.value;
    settingsDirty = true;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
});

function openModal(id) {
  $(id).classList.add("open");
  $(id).setAttribute("aria-hidden", "false");
}

function closeModal(id) {
  $(id).classList.remove("open");
  $(id).setAttribute("aria-hidden", "true");
}

$("instructionsBtn").addEventListener("click", () => openModal("instructionsModal"));
$("closeInstructionsBtn").addEventListener("click", () => closeModal("instructionsModal"));
$("instructionsModal").addEventListener("click", (event) => {
  if (event.target.id === "instructionsModal") {
    closeModal("instructionsModal");
  }
});

$("thanksBtn").addEventListener("click", () => {
  openModal("thanksModal");
});

$("closeThanksBtn").addEventListener("click", () => {
  closeModal("thanksModal");
});

$("thanksModal").addEventListener("click", (event) => {
  if (event.target.id === "thanksModal") {
    closeModal("thanksModal");
  }
});

renderDelayEfficiency();
renderMarquee();
refresh();
setInterval(refresh, 1000);
setInterval(renderMarquee, 1000);
