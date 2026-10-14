import { execFileSync } from "node:child_process";
import { randomUUID } from "node:crypto";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";

type Role =
  | "ADMIN"
  | "REVIEWER"
  | "AUDITOR"
  | "OPERATOR"
  | "CROSS_TENANT_REVIEWER";
type Credentials = { tenant: string; username: string; password: string };

let flow: {
  projectId: string;
  documentId: string;
  reviewTaskId: string;
  runId: string;
  reportId: string;
} | null = null;

function credentials(role: Role): Credentials {
  return {
    tenant: process.env[`E2E_${role}_TENANT`]!,
    username: process.env[`E2E_${role}_USERNAME`]!,
    password: process.env[`E2E_${role}_PASSWORD`]!,
  };
}

async function signIn(
  page: Page,
  identity: Credentials,
  baseUrl = process.env.E2E_BASE_URL!,
) {
  await page.goto(`${baseUrl}/login`);
  await page.getByLabel("租户编号").fill(identity.tenant);
  await page.getByLabel("用户名").fill(identity.username);
  await page.getByLabel("密码").fill(identity.password);
  const loginResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/auth/token") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "登录" }).click();
  const loginResponse = await loginResponsePromise;
  expect(loginResponse.status(), await loginResponse.text()).toBe(200);
  await expect(page).toHaveURL(/\/projects$/);
}

function persisted(command: string, ...args: string[]) {
  const root = resolve(import.meta.dirname, "../../..");
  const localPython = resolve(
    root,
    process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python",
  );
  const python = process.env.E2E_PYTHON || (existsSync(localPython) ? localPython : "python");
  const raw = execFileSync(
    python,
    [resolve(root, "scripts/assert_task0011_e2e.py"), command, ...args],
    { cwd: root, env: process.env, encoding: "utf8", maxBuffer: 2_000_000 },
  );
  return JSON.parse(raw) as Record<string, unknown>;
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

test("无效凭据显示真实 401 和中文登录错误", async ({ page }) => {
  await page.goto("/login");
  await page.getByLabel("租户编号").fill(credentials("REVIEWER").tenant);
  await page.getByLabel("用户名").fill(credentials("REVIEWER").username);
  await page.getByLabel("密码").fill(`invalid-${randomUUID()}`);
  await page.getByLabel("密码").press("Enter");
  await expect(page.getByRole("alert")).toContainText("登录状态已失效，请重新登录。");
  await expect(page).toHaveURL(/\/login$/);
});

test("管理员在浏览器发布法规和配置版本并处理 409", async ({ page, request }) => {
  test.setTimeout(180_000);
  await signIn(page, credentials("ADMIN"));
  await page.getByRole("link", { name: "配置版本" }).click();
  await expect(page.getByRole("heading", { name: "法规与审查配置管理" })).toBeVisible();

  await page.getByLabel("法规操作说明").fill("TASK-0011 浏览器端法规快照验收");
  await page.getByRole("button", { name: "创建法规草稿" }).click();
  await expect(page.locator(".notice-success")).toContainText("法规修订草稿已保存");
  await page.getByRole("button", { name: "发布草稿" }).click();
  await expect(page.locator(".notice-success")).toContainText("法规版本已发布");

  const baseUrl = process.env.E2E_BASE_URL!;
  const token = await page.evaluate(() =>
    sessionStorage.getItem("bidding-compliance.access-token"),
  );
  expect(token).toBeTruthy();
  const auth = { Authorization: `Bearer ${token}` };
  const [catalogResponse, legalResponse] = await Promise.all([
    request.get(`${baseUrl}/api/v1/admin/configurations/catalog`, { headers: auth }),
    request.get(`${baseUrl}/api/v1/admin/legal`, { headers: auth }),
  ]);
  expect(catalogResponse.status()).toBe(200);
  expect(legalResponse.status()).toBe(200);
  const catalog = await catalogResponse.json();
  const legal = await legalResponse.json();
  expect(legal.publication_id).toBeTruthy();
  expect(
    legal.publications.some(
      (publication: { actor_id: string; operation: string }) =>
        publication.actor_id === "admin" && publication.operation === "publish",
    ),
  ).toBeTruthy();

  const competingDraft = await request.post(
    `${baseUrl}/api/v1/admin/configurations/drafts`,
    {
      headers: auth,
      data: {
        request_id: randomUUID(),
        expected_sequence: 0,
        expected_draft_sequence: 0,
        expected_legal_publication_id: legal.publication_id,
        skill_ids: catalog.skills.map((item: { skill_id: string }) => item.skill_id),
        model_policy: catalog.model_policy,
        reason: "并发状态更新，用于浏览器冲突验收",
      },
    },
  );
  expect(competingDraft.status()).toBe(201);

  await page.getByLabel("配置变更说明").fill("TASK-0011 浏览器端配置发布验收");
  const createDraft = page.getByRole("button", { name: "保存配置草稿" });
  await createDraft.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("alert")).toContainText(
    "数据已被其他操作更新，请刷新后重新确认。",
  );

  await page.getByRole("button", { name: "刷新状态" }).click();
  const refreshedConfigResponse = await request.get(
    `${baseUrl}/api/v1/admin/configurations`,
    { headers: auth },
  );
  expect(refreshedConfigResponse.status()).toBe(200);
  const refreshedConfig = await refreshedConfigResponse.json();
  expect(refreshedConfig.draft_revision_id).toBeTruthy();
  expect(
    refreshedConfig.items.some(
      (item: { revision_id: string; status: string }) =>
        item.revision_id === refreshedConfig.draft_revision_id && item.status === "draft",
    ),
  ).toBeTruthy();
  const publishConfig = page.getByRole("button", { name: "发布配置" });
  await expect(publishConfig).toBeEnabled();
  const publishResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith("/api/v1/admin/configurations/publish") &&
      response.request().method() === "POST",
  );
  await publishConfig.click();
  const publishResponse = await publishResponsePromise;
  expect(publishResponse.status()).toBe(200);
  await expect(page.locator(".notice-success")).toContainText("审查配置已发布");
  await expect(page.getByText("当前版本：v1")).toBeVisible();
  await expect(page.getByLabel(/API Key/i)).toHaveCount(0);
  await expect(page.getByText(/\bsk-[a-z0-9]{20,}\b/i)).toHaveCount(0);
});

test("审核员通过真实服务完成项目、上传、复核、发布与报告下载", async ({ page, request }) => {
  test.setTimeout(15 * 60 * 1000);
  await signIn(page, credentials("REVIEWER"));

  await page.getByRole("button", { name: /新建项目/ }).first().click();
  const projectDialog = page.getByRole("dialog", { name: "新建项目" });
  const unique = `TASK-0011 合成验收 ${new Date().toISOString()} ${randomUUID().slice(0, 8)}`;
  await projectDialog.getByLabel(/项目名称/).fill(unique);
  await projectDialog.getByLabel(/采购类型/).selectOption("government");
  await projectDialog.getByLabel(/项目类型/).selectOption("goods");
  await projectDialog.getByLabel(/地区/).fill("合成测试地区");
  await projectDialog.getByRole("button", { name: "保存项目" }).click();
  const projectLink = page.getByRole("link", { name: new RegExp(unique) });
  await expect(projectLink).toBeVisible();
  const projectPath = await projectLink.getAttribute("href");
  expect(projectPath).toMatch(/^\/projects\//);
  const projectId = decodeURIComponent(projectPath!.split("/").at(-1)!);

  const baseUrl = process.env.E2E_BASE_URL!;
  const reviewerToken = await page.evaluate(() =>
    sessionStorage.getItem("bidding-compliance.access-token"),
  );
  expect(reviewerToken).toBeTruthy();
  const updateBody = {
    name: unique,
    procurement_type: "government",
    project_type: "goods",
    region: "合成测试地区",
    expected_version: 1,
  };
  const firstUpdate = await request.put(`${baseUrl}/api/v1/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${reviewerToken}` },
    data: updateBody,
  });
  expect(firstUpdate.status()).toBe(200);
  const staleUpdate = await request.put(`${baseUrl}/api/v1/projects/${projectId}`, {
    headers: { Authorization: `Bearer ${reviewerToken}` },
    data: updateBody,
  });
  expect(staleUpdate.status()).toBe(409);

  await page.getByRole("button", { name: /新建项目/ }).first().click();
  await expect(page.getByRole("dialog", { name: "新建项目" })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog", { name: "新建项目" })).toBeHidden();
  await projectLink.click();

  await page.locator("#tender-file").setInputFiles({
    name: "synthetic-tender.docx",
    mimeType:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: syntheticDocx(),
  });
  const uploadResponsePromise = page.waitForResponse(
    (response) =>
      response.url().includes("/documents") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "上传文件" }).click();
  const uploadResponse = await uploadResponsePromise;
  expect([201, 202]).toContain(uploadResponse.status());
  const uploaded = await uploadResponse.json();
  const documentId = uploaded.document_id as string;
  expect(documentId).toBeTruthy();
  await expect(page.getByText("文件已接收", { exact: false })).toBeVisible();

  const workerPath = resolve(import.meta.dirname, "../../../scripts/process_document.py");
  const python = process.env.E2E_PYTHON!;
  try {
    execFileSync(python, [workerPath, "--tenant", "tenant-a", "--document", documentId], {
      cwd: resolve(import.meta.dirname, "../../.."),
      env: process.env,
      timeout: 6 * 60 * 1000,
      maxBuffer: 5_000_000,
    });
  } catch (error) {
    const output = error as { stdout?: Buffer; stderr?: Buffer; message?: string };
    throw new Error(
      `The real document worker failed: ${output.message ?? "unknown error"}\n${output.stdout?.toString("utf8") ?? ""}\n${output.stderr?.toString("utf8") ?? ""}`,
    );
  }

  const documentTable = page.getByRole("region", { name: "项目招标文件列表" });
  const row = documentTable.getByRole("row").filter({ hasText: documentId });
  const status = row.locator(".status-badge");
  await expect.poll(async () => status.textContent(), { timeout: 180_000 }).toMatch(
    /可用于审查|等待上下文确认|需要人工检查|处理失败/,
  );
  if ((await status.textContent()) === "等待上下文确认") {
    await row.getByRole("button", { name: "查看上下文" }).click();
    const dialog = page.getByRole("dialog", { name: "文档上下文与处理记录" });
    await dialog.getByLabel(/确认理由/).fill("使用合成项目资料核对文档处理上下文");
    const contextResponsePromise = page.waitForResponse(
      (response) =>
        response.url().includes(`/documents/${documentId}/context`) &&
        response.request().method() === "POST",
    );
    await dialog.getByRole("button", { name: "确认上下文" }).click();
    const contextResponse = await contextResponsePromise;
    expect(contextResponse.status()).toBe(200);
  }
  await expect(status).toHaveText("可用于审查", { timeout: 180_000 });
  const selection = row.getByRole("checkbox", { name: /选择文档/ });
  await expect(selection).toBeEnabled();
  await selection.check();
  const reviewResponsePromise = page.waitForResponse(
    (response) =>
      response.url().endsWith(`/api/v1/projects/${projectId}/reviews`) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "发起审查" }).click();
  const reviewResponse = await reviewResponsePromise;
  expect(
    reviewResponse.status(),
    `ReviewEngine response: ${await reviewResponse.text()}`,
  ).toBe(202);
  const createdReview = await reviewResponse.json();
  expect(createdReview.status).toBe("waiting_human");
  const reviewTaskId = createdReview.review_task_id as string;
  const runId = createdReview.run_id as string;
  await expect(page).toHaveURL(
    new RegExp(`/reviews/${reviewTaskId}/${runId}$`),
    { timeout: 30_000 },
  );
  await expect(page.getByRole("heading", { name: "审查任务详情" })).toBeVisible();
  await expect(page.locator(".status-badge").first()).toHaveText("等待人工复核");

  const findings = page.locator(".finding-card");
  let exactCitationCount = 0;
  for (let index = 0; index < (await findings.count()); index += 1) {
    const card = findings.nth(index);
    const citations = page.waitForResponse(
      (response) => response.url().includes("/citations") && response.status() === 200,
    );
    await card.getByRole("button", { name: "查询服务端精确定位" }).click();
    await citations;
    await expect(card.locator(".citation-list, .citation-actions .muted")).toBeVisible();
    const citationCount = await card.locator(".citation-list .citation-card").count();
    exactCitationCount += citationCount;
    if (citationCount > 0) {
      const sourceDownload = page.waitForEvent("download");
      await card.getByRole("button", { name: "下载原文" }).first().click();
      expect((await sourceDownload).suggestedFilename()).toContain("原始证据-");
    }
    if (await card.getByRole("button", { name: "保存复核决定" }).count()) {
      await card.getByLabel("复核理由").fill("根据合成文档和服务端原文定位进行人工核验");
      await card.getByRole("button", { name: "保存复核决定" }).click();
      await expect(card.getByRole("button", { name: "保存复核决定" })).toHaveCount(0);
    }
  }
  expect(exactCitationCount).toBeGreaterThan(0);
  if (await page.getByRole("button", { name: "确认本次无待复核项目" }).count()) {
    await page.getByLabel("确认理由").fill("复核合成结果后确认没有待复核项目");
    await page.getByRole("button", { name: "确认本次无待复核项目" }).click();
  }
  await page.getByRole("button", { name: "继续审查流程" }).click();
  await expect(page.locator(".notice-success")).toContainText("结果已发布");
  await expect(page.locator(".status-badge").first()).toHaveText("结果已发布");
  await expect(page.getByRole("heading", { name: "结果版本与报告" })).toBeVisible();

  await page.getByRole("button", { name: "生成 Word" }).click();
  const wordRow = page.getByRole("row").filter({ hasText: "DOCX" }).last();
  await expect(wordRow).toBeVisible();
  const wordDownload = page.waitForEvent("download");
  await wordRow.getByRole("button", { name: "下载报告" }).click();
  expect((await wordDownload).suggestedFilename()).toMatch(/\.docx$/);
  await page.getByRole("button", { name: "生成 PDF" }).click();
  const pdfRow = page.getByRole("row").filter({ hasText: "PDF" }).last();
  await expect(pdfRow).toBeVisible();
  const pdfDownload = page.waitForEvent("download");
  await pdfRow.getByRole("button", { name: "下载报告" }).click();
  expect((await pdfDownload).suggestedFilename()).toMatch(/\.pdf$/);
  const reportId = (await pdfRow.locator("code").first().textContent())!.trim();
  flow = { projectId, documentId, reviewTaskId, runId, reportId };

  const evidence = persisted(
    "assert-flow",
    "--tenant",
    "tenant-a",
    "--project",
    projectId,
    "--document",
    documentId,
    "--task",
    reviewTaskId,
    "--run-id",
    runId,
  );
  expect(evidence.document_status).toBe("ready");
  expect(evidence.review_run_status).toBe("result_published");
  expect(evidence.review_task_record_status).toBe("running");
  expect(evidence.report_formats).toEqual(["docx", "pdf"]);
  expect(evidence.configuration_revision_id).toBeTruthy();
});

test("审计查询、角色权限、跨租户隔离和无执行器 503 均由真实后端返回", async ({
  page,
  request,
}) => {
  test.setTimeout(180_000);
  expect(flow).not.toBeNull();

  await signIn(page, credentials("AUDITOR"));
  await page.getByRole("link", { name: "审计记录" }).click();
  await expect(page.getByRole("heading", { name: "审计记录" })).toBeVisible();
  await page.getByLabel("操作类型").fill("project.updated");
  await page.getByRole("button", { name: "查询记录" }).click();
  await expect(page.getByRole("table")).toContainText("project.updated");
  const auditEvidence = persisted("assert-audit", "--tenant", "tenant-a", "--actor", "auditor");
  expect(auditEvidence.audit_query_event_id).toBeTruthy();

  await page.getByRole("button", { name: "退出登录" }).click();
  await signIn(page, credentials("OPERATOR"));
  await page.goto(`${process.env.E2E_BASE_URL!}/configurations`);
  await expect(page.getByText("当前账号无权访问配置管理。", { exact: true })).toBeVisible();
  const operatorToken = await page.evaluate(() =>
    sessionStorage.getItem("bidding-compliance.access-token"),
  );
  const baseUrl = process.env.E2E_BASE_URL!;
  const configDenied = await request.get(`${baseUrl}/api/v1/admin/configurations`, {
    headers: { Authorization: `Bearer ${operatorToken}` },
  });
  expect(configDenied.status()).toBe(403);
  const exportDenied = await request.get(
    `${baseUrl}/api/v1/reports/${flow!.reportId}/content`,
    { headers: { Authorization: `Bearer ${operatorToken}` } },
  );
  expect(exportDenied.status()).toBe(403);

  const crossTenant = credentials("CROSS_TENANT_REVIEWER");
  const crossTenantLogin = await request.post(`${baseUrl}/api/v1/auth/token`, {
    data: {
      tenant_id: crossTenant.tenant,
      username: crossTenant.username,
      password: crossTenant.password,
    },
  });
  expect(crossTenantLogin.status()).toBe(200);
  const crossTenantToken = (await crossTenantLogin.json()).access_token as string;
  const crossTenantIdentity = await request.get(`${baseUrl}/api/v1/auth/me`, {
    headers: { Authorization: `Bearer ${crossTenantToken}` },
  });
  expect(crossTenantIdentity.status()).toBe(200);
  expect(await crossTenantIdentity.json()).toMatchObject({
    tenant_id: "tenant-b",
    role: "reviewer",
  });
  const crossTenantProject = await request.get(
    `${baseUrl}/api/v1/projects/${flow!.projectId}`,
    { headers: { Authorization: `Bearer ${crossTenantToken}` } },
  );
  const crossTenantStatus = crossTenantProject.status();
  expect(crossTenantStatus).toBe(404);

  const noReviewBase = process.env.E2E_NO_REVIEW_BASE_URL!;
  const before = persisted("stats").review_run_count;
  const noReviewPage = await page.context().newPage();
  await signIn(noReviewPage, credentials("REVIEWER"), noReviewBase);
  await noReviewPage.goto(`${noReviewBase}/projects/${encodeURIComponent(flow!.projectId)}`);
  const documentRow = noReviewPage
    .getByRole("region", { name: "项目招标文件列表" })
    .getByRole("row")
    .filter({ hasText: flow!.documentId });
  await documentRow.getByRole("checkbox", { name: /选择文档/ }).check();
  await noReviewPage.getByRole("button", { name: "发起审查" }).click();
  await expect(noReviewPage.getByRole("alert")).toContainText(
    "审查执行服务当前不可用，系统没有生成模拟结果。",
  );
  const after = persisted("stats").review_run_count;
  expect(after).toBe(before);
});

test("管理员撤销账号后旧浏览器会话立即失效", async ({ page }) => {
  await signIn(page, credentials("REVIEWER"));
  persisted("revoke-user", "--tenant", "tenant-a", "--user", "reviewer");
  await page.reload();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("alert")).toContainText("登录状态已失效，请重新登录。");
});
