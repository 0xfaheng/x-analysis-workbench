// X 账号周报采集：在 ego-browser 中读取 Creator Studio 资格页并导出 Analytics CSV。
// 由 run_weekly.py 在前面注入 `const OUT_DIR = "...";` `const HANDLE = "...";` 后经 stdin 交给 `ego-browser nodejs`
// （ego 的 Node 运行时拿不到外部环境变量）。只读，不发帖、不改设置；未登录时直接停止。

const fs = await import("node:fs/promises");
const path = await import("node:path");
const meta = { started_at: new Date().toISOString(), handle: HANDLE, files: {}, warnings: [], backend: "ego" };
const writeMeta = (extra = {}) =>
  fs.writeFile(path.join(OUT_DIR, "meta.json"), JSON.stringify({ ...meta, ...extra }, null, 2), "utf8");

let task, page;
let step = "初始化";

async function mainText() {
  return page.evaluate(() => (document.querySelector("main") || document.body).innerText);
}

async function selectRange(label) {
  await page.click(`text="${label}" >> nth=0`, { label: `select ${label} range` });
  await page.waitForTimeout(4000);
}

async function setVerifiedOnly(want) {
  const state = await page.evaluate(() => {
    const b = document.querySelector("main button[aria-label='Verified only']");
    return b ? b.getAttribute("aria-pressed") : null;
  });
  if (state === null) {
    meta.warnings.push("Verified only 开关未找到");
    return false;
  }
  if ((state === "true") !== want) {
    await page.click("loc=role:button[name='Verified only']", { label: "toggle verified only" });
    await page.waitForTimeout(5000);
  }
  return true;
}

async function downloadCsv(name) {
  step = `下载 ${name}`;
  // 同时挂上两个异常处理，点击失败时下载超时也不会成为未处理的拒绝。
  const [d] = await Promise.all([
    page.waitForEvent("download", { timeout: 45000 }),
    page.click("loc=css:button[aria-label='Download CSV'] >> nth=0", { label: "download analytics csv" }),
  ]);
  const out = path.join(OUT_DIR, name);
  await d.saveAs(out);
  meta.files[name] = d.suggestedFilename();
}

async function collect() {
  await fs.mkdir(OUT_DIR, { recursive: true });
  await writeMeta({ ok: false, reason: "in_progress" });
  step = "创建任务空间";
  task = await taskSpace("X 周报采集");
  meta.space_id = task.spaceId;
  page = task.page("p1");

  // 1. 登录检查
  step = "登录检查";
  await page.goto("https://x.com/home");
  await page.waitForSelector("loc=css:[data-testid='SideNav_AccountSwitcher_Button']", { timeout: 25000 }).catch(() => {});
  const acct = await page.evaluate(
    () => document.querySelector("[data-testid='SideNav_AccountSwitcher_Button']")?.innerText || null,
  );
  if (!acct || !acct.toLowerCase().includes("@" + HANDLE.toLowerCase())) {
    await writeMeta({ ok: false, reason: "not_logged_in", account_seen: acct, finished_at: new Date().toISOString() });
    console.log(JSON.stringify({ ok: false, reason: "not_logged_in", account_seen: acct }));
    return 3;
  }

  // 2. 原创内容奖励资格页
  step = "收益资格页";
  await page.goto("https://x.com/i/jf/creators/original_content_rewards");
  await page.waitForTimeout(7000);
  const eligibility = await page.evaluate(() => {
    const main = document.querySelector("main") || document.body;
    // 以状态图标（实心对勾 = 已满足，圆圈叉号 = 未满足）定位清单项，再取同一行的文字
    const STATUS = ["M12 1.75C6.34", "M12 3.75c"];
    const items = [...main.querySelectorAll("svg")]
      .map((s) => ({ s, d: s.querySelector("path")?.getAttribute("d") || "" }))
      .filter(({ d }) => STATUS.some((pre) => d.startsWith(pre)))
      .map(({ s, d }) => {
        let c = s.parentElement;
        while (c && c !== main && !c.querySelector("p")) c = c.parentElement;
        return { text: c?.querySelector("p")?.innerText.trim() || "", icon: d.slice(0, 16) };
      })
      .filter((it) => it.text);
    return { text: main.innerText, items };
  });
  await fs.writeFile(path.join(OUT_DIR, "eligibility.json"), JSON.stringify(eligibility, null, 2), "utf8");

  // 3. 账号概览：近 3 个月，全部用户 + 仅认证用户
  step = "账号概览";
  await page.goto("https://x.com/i/account_analytics");
  await page.waitForTimeout(8000);
  await setVerifiedOnly(false);
  await selectRange("3M");
  await fs.writeFile(path.join(OUT_DIR, "overview_all_3m.txt"), await mainText(), "utf8");
  await downloadCsv("overview_all.csv");
  step = "认证用户概览";
  if (await setVerifiedOnly(true)) {
    await fs.writeFile(path.join(OUT_DIR, "overview_verified_3m.txt"), await mainText(), "utf8");
    await downloadCsv("overview_verified.csv");
    step = "恢复全部用户概览";
    await setVerifiedOnly(false);
  }

  // 4. 帖子明细：近 90 天（含回复，分析时区分）
  step = "帖子明细页";
  await page.goto("https://x.com/i/account_analytics/content?type=posts&sort=date&dir=desc&days=90");
  await page.waitForTimeout(8000);
  await downloadCsv("content_90d.csv");

  // 5. 受众画像（文本快照，供参考）
  step = "受众画像";
  await page.goto("https://x.com/i/account_analytics/audience");
  await page.waitForTimeout(7000);
  await selectRange("28D").catch(() => meta.warnings.push("受众页 28D 切换失败，保留默认范围"));
  await fs.writeFile(path.join(OUT_DIR, "audience.txt"), await mainText(), "utf8");

  step = "保存采集结果";
  await writeMeta({ ok: true, finished_at: new Date().toISOString() });
  return 0;
}

async function recordError(error) {
  const message = error?.message || String(error);
  const failure = { ok: false, reason: "error", error: message, step, finished_at: new Date().toISOString() };
  try {
    await writeMeta(failure);
  } catch (metaError) {
    console.error(`无法保存 meta.json：${metaError?.message || String(metaError)}`);
  }
  console.error(JSON.stringify(failure));
}

let exitCode = 0;
try {
  exitCode = await collect();
} catch (error) {
  exitCode = 4;
  await recordError(error);
} finally {
  if (task) {
    try {
      await task.finish({ keep: [] });
    } catch (error) {
      // 已有失败保留原始原因；未登录的退出码 3 也不能被清理失败覆盖。
      if (exitCode !== 0) console.error(`任务空间清理失败：${error?.message || String(error)}`);
      else {
        exitCode = 4;
        step = "关闭任务空间";
        await recordError(error);
      }
    }
  }
}
if (exitCode) process.exit(exitCode);
console.log(JSON.stringify({ ok: true, out: OUT_DIR, files: meta.files, warnings: meta.warnings }));
