import { execFileSync } from "node:child_process";
import { expect, test, type Page } from "@playwright/test";
import { existsSync } from "node:fs";
import { resolve } from "node:path";

type Credentials = { tenant: string; username: string; password: string };

function credentials(role: "REVIEWER" | "AUDITOR" | "OPERATOR"): Credentials {
  return {
    tenant: process.env[`E2E_${role}_TENANT`]!,
    username: process.env[`E2E_${role}_USERNAME`]!,
    password: process.env[`E2E_${role}_PASSWORD`]!,
  };
}

async function signIn(page: Page, identity: Credentials) {
  await page.goto("/login");
  await page.getByLabel("租户编号").fill(identity.tenant);
  await page.getByLabel("用户名").fill(identity.username);
  await page.getByLabel("密码").fill(identity.password);
  await page.getByLabel("密码").press("Enter");
  await expect(page).toHaveURL(/\/projects$/);
}

function syntheticDocx(): Buffer {
  const repositoryRoot = resolve(import.meta.dirname, "../../..");
  const localPython = resolve(
    repositoryRoot,
    process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python",
  );
  const python = process.env.E2E_PYTHON || (existsSync(localPython) ? localPython : "python");
  const script = [
    "from io import BytesIO",
    "import sys",
    "from docx import Document",
    "document = Document()",
    "document.add_heading('资格要求', level=1)",
    "document.add_paragraph('投标人必须在本市注册。该条款仅供隔离测试使用。')",
    "buffer = BytesIO()",
    "document.save(buffer)",
    "sys.stdout.buffer.write(buffer.getvalue())",
  ].join("\n");
  return execFileSync(python, ["-c", script], { maxBuffer: 5_000_000 });
}

test("reviewer completes the browser workflow and server roles remain authoritative", async ({ page, request }) => {
  test.setTimeout(15 * 60 * 1000);
  await signIn(page, credentials("REVIEWER"));

  await page.getByRole("button", { name: /新建项目/ }).first().click();
  const projectDialog = page.getByRole("dialog", { name: "新建项目" });
  const unique = `E2E 验收项目 ${new Date().toISOString()} ${Math.random().toString(16).slice(2, 8)}`;
  await projectDialog.getByLabel(/项目名称/).fill(unique);
  await projectDialog.getByLabel(/采购类型/).selectOption("government");
  await projectDialog.getByLabel(/项目类型/).selectOption("goods");
  await projectDialog.getByLabel(/地区/).fill("合成测试地区");
  await projectDialog.getByRole("button", { name: "保存项目" }).click();
  const projectLink = page.getByRole("link", { name: new RegExp(unique) });
  await expect(projectLink).toBeVisible();
  await page.getByRole("button", { name: /新建项目/ }).first().click();
  await expect(page.getByRole("dialog", { name: "新建项目" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "新建项目" })).toBeHidden();
  await projectLink.click();

  await page.locator("#tender-file").setInputFiles({
    name: "synthetic-tender.docx",
    mimeType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: syntheticDocx(),
  });
  await page.getByRole("button", { name: "上传文件" }).click();
  await expect(page.getByText("文件已接收", { exact: false })).toBeVisible();
  const documentTable = page.getByRole("region", { name: "项目招标文件列表" });
  const row = documentTable.getByRole("row").nth(1);
  const status = row.locator(".status-badge");
  await expect.poll(async () => {
    return status.textContent();
  }, { timeout: 180_000 }).toMatch(/可用于审查|等待上下文确认|需要人工检查|处理失败/);

  if (await status.textContent() === "等待上下文确认") {
    await row.getByRole("button", { name: "查看上下文" }).click();
    const dialog = page.getByRole("dialog", { name: "文档上下文与处理记录" });
    await dialog.getByLabel(/确认理由/).fill("在隔离端到端测试中根据合成项目资料核对");
    await dialog.getByRole("button", { name: "确认上下文" }).click();
  }
  await expect(status).toHaveText("可用于审查", { timeout: 180_000 });
  const reviewSelection = page.getByRole("checkbox", { name: /选择文档/ }).first();
  await expect(reviewSelection).toBeEnabled();
  await reviewSelection.check();
  await page.getByRole("button", { name: "发起审查" }).click();
  await expect(page.getByText(/审查执行服务当前不可用/)).toHaveCount(0, { timeout: 30_000 });
  const taskRow = page.getByRole("row").filter({ has: page.getByRole("link", { name: "打开任务" }) }).first();
  await expect(taskRow).toBeVisible({ timeout: 600_000 });
  await expect(taskRow.locator(".status-badge")).toHaveText("等待人工复核", { timeout: 600_000 });
  await taskRow.getByRole("link", { name: "打开任务" }).click();

  const findingCards = page.locator(".finding-card");
  let exactCitationCount = 0;
  for (let index = 0; index < await findingCards.count(); index += 1) {
    const card = findingCards.nth(index);
    const citationsResponse = page.waitForResponse((response) => response.url().includes("/citations") && response.status() === 200);
    await card.getByRole("button", { name: "查询服务端精确定位" }).click();
    await citationsResponse;
    await expect(card.locator(".citation-list, .citation-actions .muted")).toBeVisible();
    const locationCount = await card.locator(".citation-list .citation-card").count();
    exactCitationCount += locationCount;
    if (locationCount > 0) {
      const sourceDownload = page.waitForEvent("download");
      await card.getByRole("button", { name: "下载原文" }).first().click();
      expect((await sourceDownload).suggestedFilename()).toContain("原始证据-");
    }
    if (await card.getByRole("button", { name: "保存复核决定" }).count()) {
      await card.getByLabel("复核理由").fill("根据合成文档及服务端精确定位进行人工核验");
      await card.getByRole("button", { name: "保存复核决定" }).click();
      await expect(card.getByRole("button", { name: "保存复核决定" })).toHaveCount(0);
    }
  }
  expect(exactCitationCount).toBeGreaterThan(0);
  if (await page.getByRole("button", { name: "确认本次无待复核项目" }).count()) {
    await page.getByLabel("确认理由").fill("复核合成结果后确认无待复核项目");
    await page.getByRole("button", { name: "确认本次无待复核项目" }).click();
  }
  await page.getByRole("button", { name: "继续审查流程" }).click();
  await expect(page.getByRole("heading", { name: "结果版本与报告" })).toBeVisible();
  await page.getByRole("button", { name: "生成 Word" }).click();
  const wordRow = page.getByRole("row").filter({ hasText: "DOCX" }).last();
  await expect(wordRow).toBeVisible();
  const wordDownload = page.waitForEvent("download");
  await wordRow.getByRole("button", { name: "下载报告" }).click();
  expect((await wordDownload).suggestedFilename()).toMatch(/\.docx$/);
  await page.getByRole("button", { name: "生成 PDF" }).click();
  const reportRow = page.getByRole("row").filter({ hasText: "PDF" }).last();
  await expect(reportRow).toBeVisible();
  const downloadPromise = page.waitForEvent("download");
  await reportRow.getByRole("button", { name: "下载报告" }).click();
  const reportDownload = await downloadPromise;
  expect(reportDownload.suggestedFilename()).toMatch(/\.pdf$/);
  const reportId = await reportRow.locator("code").first().textContent();

  await page.getByRole("button", { name: "退出登录" }).click();
  await signIn(page, credentials("AUDITOR"));
  await page.getByRole("link", { name: "审计记录" }).click();
  await expect(page.getByRole("heading", { name: "审计记录" })).toBeVisible();
  await expect(page.getByRole("table")).toBeVisible();

  await page.getByRole("button", { name: "退出登录" }).click();
  await signIn(page, credentials("OPERATOR"));
  const token = await page.evaluate(() => sessionStorage.getItem("bidding-compliance.access-token"));
  expect(token).toBeTruthy();
  const denied = await request.get(`${process.env.E2E_BASE_URL}/api/v1/reports/${reportId}/content`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  expect(denied.status()).toBe(403);
});
