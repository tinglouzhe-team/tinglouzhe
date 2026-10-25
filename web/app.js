/* 听漏者 · 前端逻辑（原生 JS，无依赖） */
(() => {
  const $ = (s) => document.querySelector(s);
  const num = (v, d = 0) =>
    v === null || v === undefined || Number.isNaN(v)
      ? "—"
      : Number(v).toLocaleString("zh-CN", { minimumFractionDigits: d, maximumFractionDigits: d });

  const state = { history: [], busy: false };

  /* ------------------------------------------------ 初始化 */
  async function init() {
    try {
      // 加时间戳，彻底绕开浏览器缓存
      const health = await fetch(`/api/health?t=${Date.now()}`, { cache: "no-store" })
        .then((r) => r.json());
      const pill = $("#mode-pill");
      if (health.mode === "llm") {
        pill.textContent = `在线模型 · ${health.model || "已就绪"}`;
        pill.classList.remove("rule");
      } else {
        pill.textContent = "本地规则模式 · 离线可用";
        pill.classList.add("rule");
      }
      // 页脚显示"这是哪个进程"，用来确认你打开的就是刚启动的那个
      const inst = $("#instance");
      if (inst) {
        inst.textContent =
          `当前实例：端口 ${health.port ?? "?"} · 进程 ${health.pid ?? "?"} · ` +
          `${health.mode === "llm" ? "模型 " + (health.model || "已配置") : "未配置模型"}`;
      }
    } catch {
      $("#mode-pill").textContent = "服务未连接";
    }

    try {
      const data = await fetch("/api/network").then((r) => r.json());
      renderZones(data.gap);
      renderLeaks(data.rank);
      renderNetwork(data.zones, data.gap);
    } catch (e) {
      console.error(e);
    }
  }

  /* ------------------------------------------------ 管网图 */
  function renderNetwork(zones, gap) {
    const svg = $("#network");
    const shares = (gap.zones || []).map((z) => z.share_of_total_gap || 0);
    const maxShare = Math.max(1, ...shares);
    const xs = [270, 470, 660];
    let s = "";

    // 空压机
    s += `<rect x="20" y="38" width="74" height="58" rx="10" fill="#eaf2ff" stroke="#cfe0ff"/>`;
    s += `<text x="57" y="63" text-anchor="middle" font-size="12" fill="#1f6feb">空压机</text>`;
    s += `<text x="57" y="80" text-anchor="middle" font-size="10" fill="#66748c">7-8 bar</text>`;

    // 储气罐
    s += `<rect x="112" y="30" width="62" height="74" rx="14" fill="#f4f7fc" stroke="#d7e0ee"/>`;
    s += `<text x="143" y="62" text-anchor="middle" font-size="12" fill="#33405a">储气罐</text>`;
    s += `<text x="143" y="78" text-anchor="middle" font-size="10" fill="#66748c">保压测试点</text>`;

    // 主管
    s += `<line x1="174" y1="67" x2="730" y2="67" stroke="#9fb0c9" stroke-width="6" stroke-linecap="round"/>`;
    s += `<text x="430" y="56" text-anchor="middle" font-size="10.5" fill="#66748c">工厂主管路</text>`;

    // 三个车间
    xs.forEach((x, i) => {
      const z = (gap.zones || [])[i] || { name: "-", gap: 0, gap_pct: 0 };
      const share = (gap.zones || [])[i]?.share_of_total_gap || 0;
      const hot = Math.round((share / maxShare) * 200);
      const stroke = `rgb(${220},${120 + 90 - hot / 2},${110 - hot / 3})`;
      s += `<line x1="${x}" y1="67" x2="${x}" y2="150" stroke="#9fb0c9" stroke-width="4"/>`;
      s += `<rect x="${x - 82}" y="150" width="164" height="66" rx="10"
              fill="${hot > 110 ? "#fff5f5" : "#f8fbff"}" stroke="${stroke}" stroke-width="1.5"/>`;
      s += `<text x="${x}" y="174" text-anchor="middle" font-size="12.5" fill="#1b2433">${z.name}</text>`;
      s += `<text x="${x}" y="193" text-anchor="middle" font-size="11" fill="#66748c">
              进口 ${num(z.header_flow, 1)} · 差额 ${num(z.gap, 2)}</text>`;
      s += `<text x="${x}" y="208" text-anchor="middle" font-size="11"
              fill="${hot > 110 ? "#b91c1c" : "#0f766e"}">
              占未计量 ${share}%</text>`;
    });
    svg.innerHTML = s;
  }

  /* ------------------------------------------------ 分区表 */
  function renderZones(gap) {
    const rows = gap.zones || [];
    let html = `<table><thead><tr>
      <th>区段</th><th>进口流量</th><th>支路合计</th><th>差额</th>
      <th>未计量占比</th><th>分摊</th></tr></thead><tbody>`;
    rows.forEach((z) => {
      html += `<tr>
        <td>${z.name}</td>
        <td>${num(z.header_flow, 1)}</td>
        <td>${num(z.branch_sum, 1)}</td>
        <td style="color:${z.gap > 0 ? "#b91c1c" : "#0f766e"}">${num(z.gap, 2)}</td>
        <td>${num(z.gap_pct, 1)}%</td>
        <td><div class="bar"><i style="width:${Math.min(100, z.share_of_total_gap)}%"></i></div></td>
      </tr>`;
    });
    html += "</tbody></table>";
    $("#zone-table").innerHTML = html;
    $("#zone-note").textContent = (gap.warnings || []).join(" ");
  }

  /* ------------------------------------------------ 漏点清单 */
  function renderLeaks(rank) {
    const top = rank.top || [];
    let html = "";
    top.forEach((it, i) => {
      html += `<div class="leak ${i === 0 ? "top" : ""}">
        <span class="rank">${it.rank}</span>
        <span class="loc">${it.location}</span>
        <span class="num">漏 ${num(it.flow, 2)} m³/min</span>
        <span class="num">投 ${num(it.cost, 0)} 元</span>
        <span class="pay">${it.payback_days !== null ? num(it.payback_days, 0) + " 天回本" : "—"}</span>
      </div>`;
    });
    const s = rank.top_summary || {};
    html += `<div class="note" style="color:#0f766e">
      先修这 ${s.count} 处：投资 ${num(s.invest, 0)} 元，年省 ${num(s.annual_save, 0)} 元，
      合计减少漏气 ${num(s.flow, 2)} m³/min。</div>`;
    $("#leak-list").innerHTML = html;
  }

  /* ------------------------------------------------ 保压测算 */
  $("#btn-demo").addEventListener("click", () => {
    const f = $("#decay-form");
    f.v_m3.value = 10; f.p1_bar.value = 7; f.p2_bar.value = 6;
    f.t_min.value = 5; f.supply_flow.value = 8;
  });

  $("#decay-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const f = e.target;
    const body = {
      v_m3: +f.v_m3.value, p1_bar: +f.p1_bar.value, p2_bar: +f.p2_bar.value,
      t_min: +f.t_min.value,
      supply_flow: f.supply_flow.value ? +f.supply_flow.value : null,
      specific_power: +f.specific_power.value, hours: +f.hours.value, price: +f.price.value,
    };
    const box = $("#decay-result");
    box.className = "result";
    box.textContent = "计算中…";
    try {
      const r = await fetch("/api/decay", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then((x) => x.json());
      if (r.error) throw new Error(r.error);
      renderDecay(r);
    } catch (err) {
      box.className = "result";
      box.innerHTML = `<span style="color:#b91c1c">${err.message}</span>`;
    }
  });

  function renderDecay(r) {
    const g = r.grade || null;
    $("#decay-result").innerHTML = `
      <div class="kpis">
        <div class="kpi"><div class="k">泄漏量</div>
          <div class="v">${num(r.leak_flow_m3min, 2)}<small> m³/min</small></div></div>
        <div class="kpi"><div class="k">年耗电</div>
          <div class="v">${num(r.annual_kwh, 0)}<small> kWh</small></div></div>
        <div class="kpi"><div class="k">年损失</div>
          <div class="v">${num(r.annual_cost, 0)}<small> 元</small></div></div>
      </div>
      <div>年漏气 <b>${num(r.annual_volume_m3, 0)}</b> m³ ·
           年减碳 <b>${num(r.annual_co2_t, 1)}</b> tCO₂
           ${g ? ` · 泄漏率 <b>${num(r.leak_rate, 1)}%</b>
           <span class="grade ${g.level}">${g.level}</span> ${g.note}` : ""}</div>
      <div style="margin-top:6px;color:#66748c;font-size:12px">
        假设：比功率 ${r.assumptions.specific_power_kwh_m3} kWh/m³ ·
        年运行 ${num(r.assumptions.hours_per_year, 0)} h ·
        电价 ${r.assumptions.price_yuan_kwh} 元/kWh
      </div>
      ${(r.warnings || []).map((w) => `<div class="warnline">⚠ ${w}</div>`).join("")}
    `;
  }

  /* ------------------------------------------------ 对话 */
  function addMsg(role, text, trace) {
    const wrap = document.createElement("div");
    wrap.className = `msg ${role}`;
    let inner = `<div class="bubble">${escapeHtml(text)}`;
    if (trace && trace.length) {
      const names = trace.map((t) => t.tool).join(" → ");
      inner += `<div class="trace">⚙ 调用工具：${names}</div>`;
    }
    inner += "</div>";
    wrap.innerHTML = inner;
    $("#messages").appendChild(wrap);
    $("#messages").scrollTop = $("#messages").scrollHeight;
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  async function send(text) {
    if (!text.trim() || state.busy) return;
    state.busy = true;
    addMsg("user", text);
    state.history.push({ role: "user", content: text });
    const btn = $("#chat-form button");
    btn.disabled = true;
    try {
      const r = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages: state.history.slice(-10) }),
      }).then((x) => x.json());
      addMsg("bot", r.reply || "（没有返回内容）", r.trace);
      state.history.push({ role: "assistant", content: r.reply || "" });
    } catch (e) {
      addMsg("bot", "服务没响应，检查一下 app.py 是否还在运行。");
    } finally {
      state.busy = false;
      btn.disabled = false;
    }
  }

  $("#chat-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const input = $("#chat-input");
    const v = input.value;
    input.value = "";
    send(v);
  });

  document.querySelectorAll(".quick button").forEach((b) => {
    b.addEventListener("click", () => send(b.dataset.q));
  });

  $("#btn-clear").addEventListener("click", () => {
    state.history = [];
    $("#messages").innerHTML = "";
  });

  init();
})();
