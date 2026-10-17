import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { setToken } from "../api/client";
import type { components } from "../api/schema";
import { AuthProvider } from "../auth";
import { ProjectPage } from "./project";

type DocumentRecord = components["schemas"]["Document"];
type QualityCorrection = components["schemas"]["QualityCorrection"];
type ContextConfirmation = components["schemas"]["ContextConfirmation"];

const PROJECT = "project-1";
const DOCUMENT = "doc-1";
const SHA256 = "a".repeat(64);
const TEXTAREA_ONE = "片段 1";
const TEXTAREA_TWO = "片段 2";

type Call = {
  method: string;
  path: string;
  body: unknown;
  authorization: string | null;
};

function json(payload: unknown, status = 200): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function installFetch(handle: (call: Call) => Response) {
  const calls: Call[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input, init) => {
    const request = new Request(input as RequestInfo, init);
    const url = new URL(request.url);
    const raw =
      request.method === "GET" || request.method === "HEAD"
        ? null
        : await request.clone().text();
    const call: Call = {
      method: request.method,
      path: url.pathname + url.search,
      body: raw ? JSON.parse(raw) : null,
      authorization: request.headers.get("Authorization"),
    };
    calls.push(call);
    return handle(call);
  });
  return calls;
}

function projectPayload() {
  return {
    project_id: PROJECT,
    tenant_id: "tenant-a",
    name: "合成项目",
    procurement_type: "government" as const,
    project_type: "works" as const,
    region: "示例地区",
    industry: null,
    budget_amount: null,
    applicable_system: null,
    procurement_method: "unknown" as const,
    buyer_type: "unknown" as const,
    subject_type: "unknown" as const,
    legal_frameworks: [],
    version: 1,
    created_at: "2026-10-16T00:00:00+00:00",
  };
}

function documentPayload(
  overrides: Partial<DocumentRecord> = {},
): DocumentRecord {
  return {
    document_id: DOCUMENT,
    project_id: PROJECT,
    file_format: "docx",
    status: "needs_review",
    sha256: SHA256,
    media_type:
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    size_bytes: 2048,
    context_version: 1,
    parse_version: 1,
    issues: ["LOW_QUALITY"],
    ...overrides,
  };
}

function fragment(
  overrides: Partial<components["schemas"]["Fragment"]>,
): components["schemas"]["Fragment"] {
  return {
    locator: "docx/body/p/0",
    page: null,
    bbox: null,
    coordinate_system: "ooxml",
    kind: "paragraph",
    section: "",
    text: "",
    text_sha256: "b".repeat(64),
    source: "native",
    confidence: null,
    table: null,
    row: null,
    column: null,
    ...overrides,
  };
}

function renderPage() {
  setToken("test-token");
  return render(
    <MemoryRouter initialEntries={[`/projects/${PROJECT}`]}>
      <Routes>
        <Route
          path="/projects/:projectId"
          element={
            <AuthProvider>
              <ProjectPage />
            </AuthProvider>
          }
        />
      </Routes>
    </MemoryRouter>,
  );
}

/**
 * A page-level double of the API: the documents list, the parsed fragments, the recorded
 * correction and the context confirmation all move together exactly as the server does.
 */
function servingPage(handler: (call: Call) => Response | undefined) {
  return installFetch((call) => {
    if (call.method === "GET" && call.path === "/api/v1/auth/me")
      return json({
        tenant_id: "tenant-a",
        user_id: "reviewer",
        username: "reviewer",
        role: "reviewer",
      });
    const response = handler(call);
    if (!response)
      throw new Error(`unhandled request ${call.method} ${call.path}`);
    return response;
  });
}

describe("project page document repair path", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  it("takes a needs_review document to a selectable state through text and context", async () => {
    let documents = [documentPayload()];
    const sections = {
      document_id: DOCUMENT,
      parse_version: 1,
      items: [
        {
          section_id: "section-1",
          source_hash: SHA256,
          automatic: fragment({ text: "Short", kind: "paragraph" }),
          effective: fragment({ text: "Short", kind: "paragraph" }),
          revision: 1,
        },
        {
          section_id: "section-2",
          source_hash: SHA256,
          automatic: fragment({ text: "", kind: "ocr", source: "ocr" }),
          effective: fragment({ text: "", kind: "ocr", source: "ocr" }),
          revision: 1,
        },
      ],
    };
    const calls = servingPage((call) => {
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}?`)
      )
        return json(projectPayload());
      if (call.method === "GET" && call.path === `/api/v1/projects/${PROJECT}`)
        return json(projectPayload());
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/documents?`)
      )
        return json({
          items: documents,
          offset: 0,
          limit: 100,
          total: documents.length,
        });
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/reviews?`)
      )
        return json({ items: [], offset: 0, limit: 50, total: 0 });
      if (
        call.method === "GET" &&
        call.path === `/api/v1/projects/${PROJECT}/versions`
      )
        return json({ items: [projectPayload()] });
      if (
        call.method === "GET" &&
        call.path ===
          `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/sections`
      )
        return json(sections);
      if (
        call.method === "POST" &&
        call.path ===
          `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/corrections`
      ) {
        const body = call.body as QualityCorrection;
        // The correction is applied, the gate re-passes and the context version moves.
        sections.items = sections.items.map((item) => ({
          ...item,
          effective: fragment({
            ...item.effective,
            text:
              body.corrections.find(
                (correction) => correction.section_id === item.section_id,
              )?.text ?? item.effective.text,
            source: "manual",
            confidence: null,
          }),
          revision: item.revision + 1,
        }));
        sections.parse_version += 1;
        documents = [
          documentPayload({
            status: "needs_confirmation",
            parse_version: sections.parse_version,
            context_version: 2,
            issues: [],
          }),
        ];
        return json(documents[0]);
      }
      if (
        call.method === "GET" &&
        call.path ===
          `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/context`
      )
        return json({
          document_id: DOCUMENT,
          version: documents[0]?.context_version ?? 1,
          candidates: [
            {
              field: "name",
              value: "合成项目",
              confidence: 0.6,
              section_id: "section-1",
            },
          ],
          manual: null,
          confirmed: false,
          reason: null,
        });
      if (
        call.method === "POST" &&
        call.path ===
          `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/context`
      ) {
        const body = call.body as ContextConfirmation;
        if (body.expected_version !== documents[0]?.context_version)
          return json({}, 409);
        documents = [
          documentPayload({
            status: "ready",
            parse_version: sections.parse_version,
            context_version: body.expected_version + 1,
            issues: [],
          }),
        ];
        return json(documents[0]);
      }
      return undefined;
    });

    const user = userEvent.setup();
    renderPage();

    // 1) The flagged document is visible but not selectable: the gate was not loosened.
    const checkbox = await screen.findByLabelText(
      `选择文档 ${DOCUMENT} 开始审查`,
    );
    await waitFor(() => expect(checkbox).toHaveProperty("disabled", true));
    expect(screen.getByRole("button", { name: "发起审查" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByText(/另有 1 份文档解析质量不足（需人工校对）/),
    ).toBeTruthy();

    // 2) The page offers the only supported repair path.
    await user.click(screen.getByRole("button", { name: "查看/校正文本" }));
    const first = await screen.findByLabelText(new RegExp(TEXTAREA_ONE));
    const second = await screen.findByLabelText(new RegExp(TEXTAREA_TWO));
    expect(first.textContent ?? "").toContain("Short");
    expect(screen.getByText(/服务端未得到文字，需按原件转录/)).toBeTruthy();

    await user.clear(first);
    await user.type(first, "合成招标文件人工核对后的原文转录。");
    await user.type(second, "合成附件页人工转录内容。");
    await user.type(screen.getByLabelText(/校正理由/), "按纸质原件人工转录");

    await user.click(screen.getByRole("button", { name: /提交 2 处校正/ }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.path.endsWith("/corrections")).length,
      ).toBe(1),
    );
    const correction = calls.find((call) => call.path.endsWith("/corrections"));
    const correctionBody = correction?.body as QualityCorrection;
    expect(correction?.authorization).toBe("Bearer test-token");
    expect(correctionBody.expected_parse_version).toBe(1);
    expect(correctionBody.reason).toBe("按纸质原件人工转录");
    expect(correctionBody.corrections).toEqual([
      { section_id: "section-1", text: "合成招标文件人工核对后的原文转录。" },
      { section_id: "section-2", text: "合成附件页人工转录内容。" },
    ]);

    // 3) The page continues straight into the context confirmation the server now accepts.
    await user.type(
      await screen.findByLabelText(/确认理由/),
      "已核对项目资料与原件，确认上下文",
    );
    await user.click(screen.getByRole("button", { name: "确认上下文" }));
    await waitFor(() =>
      expect(
        calls.filter(
          (call) => call.method === "POST" && call.path.endsWith("/context"),
        ).length,
      ).toBe(1),
    );
    const confirmation = calls.find(
      (call) => call.method === "POST" && call.path.endsWith("/context"),
    );
    expect(confirmation?.body as ContextConfirmation).toMatchObject({
      expected_version: 2,
    });

    // 4) Only now the document becomes selectable and a review can be requested.
    await waitFor(() =>
      expect(
        screen.getByLabelText(`选择文档 ${DOCUMENT} 开始审查`),
      ).toHaveProperty("disabled", false),
    );
    expect(screen.getByText(/文本校正已记录/)).toBeTruthy();
  });

  it("keeps the repair dialog open while the server still rejects the text", async () => {
    const status: DocumentRecord["status"] = "needs_review";
    const calls = servingPage((call) => {
      if (call.method === "GET" && call.path === `/api/v1/projects/${PROJECT}`)
        return json(projectPayload());
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/documents?`)
      )
        return json({
          items: [documentPayload({ status })],
          offset: 0,
          limit: 100,
          total: 1,
        });
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/reviews?`)
      )
        return json({ items: [], offset: 0, limit: 50, total: 0 });
      if (
        call.method === "GET" &&
        call.path === `/api/v1/projects/${PROJECT}/versions`
      )
        return json({ items: [] });
      if (
        call.path ===
        `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/sections`
      )
        return json({
          document_id: DOCUMENT,
          parse_version: 1,
          items: [
            {
              section_id: "section-1",
              source_hash: SHA256,
              automatic: fragment({ text: "Short" }),
              effective: fragment({ text: "Short" }),
              revision: 1,
            },
          ],
        });
      if (call.method === "POST" && call.path.endsWith("/corrections"))
        return json(
          documentPayload({ status, parse_version: 2, context_version: 2 }),
        );
      return undefined;
    });

    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByRole("button", { name: "查看/校正文本" }),
    );
    const textarea = await screen.findByLabelText(new RegExp(TEXTAREA_ONE));
    await user.clear(textarea);
    await user.type(textarea, "仍然太短");
    await user.type(screen.getByLabelText(/校正理由/), "仍然达不到质量门槛");
    await user.click(screen.getByRole("button", { name: /提交 1 处校正/ }));
    await waitFor(() =>
      expect(
        calls.filter((call) => call.path.endsWith("/corrections")).length,
      ).toBe(1),
    );
    // The dialog stays open, says the gate did not pass and re-reads the fragments.
    expect(await screen.findByText(/质量门禁仍未通过/)).toBeTruthy();
    expect(await screen.findByLabelText(new RegExp(TEXTAREA_ONE))).toBeTruthy();
    // No context confirmation was attempted by the page.
    expect(
      calls.some(
        (call) => call.method === "POST" && call.path.endsWith("/context"),
      ),
    ).toBe(false);
  });

  it("offers no repair entry for a document the quality gate already passed", async () => {
    servingPage((call) => {
      if (call.method === "GET" && call.path === `/api/v1/projects/${PROJECT}`)
        return json(projectPayload());
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/documents?`)
      )
        return json({
          items: [
            documentPayload({
              status: "needs_confirmation",
              issues: [],
              context_version: 1,
              parse_version: 1,
            }),
          ],
          offset: 0,
          limit: 100,
          total: 1,
        });
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/reviews?`)
      )
        return json({ items: [], offset: 0, limit: 50, total: 0 });
      if (
        call.method === "GET" &&
        call.path === `/api/v1/projects/${PROJECT}/versions`
      )
        return json({ items: [] });
      return undefined;
    });
    renderPage();
    await screen.findByText("等待上下文确认");
    expect(screen.queryByRole("button", { name: "查看/校正文本" })).toBeNull();
    expect(screen.queryByText(/解析质量不足（需人工校对）/)).toBeNull();
  });
});

describe("project page per-file external authorization", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.restoreAllMocks();
    vi.unstubAllEnvs();
  });

  function servingAuthorization() {
    return servingPage((call) => {
      if (call.method === "GET" && call.path === `/api/v1/projects/${PROJECT}`)
        return json(projectPayload());
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/documents?`)
      )
        return json({
          items: [documentPayload({ status: "ready", issues: [] })],
          offset: 0,
          limit: 100,
          total: 1,
        });
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/reviews?`)
      )
        return json({ items: [], offset: 0, limit: 50, total: 0 });
      if (
        call.method === "GET" &&
        call.path === `/api/v1/projects/${PROJECT}/versions`
      )
        return json({ items: [] });
      if (
        call.method === "POST" &&
        call.path ===
          `/api/v1/projects/${PROJECT}/documents/${DOCUMENT}/external-authorization`
      ) {
        const body = call.body as { reason: string; confirmed: boolean };
        if (!body.confirmed || !body.reason.trim()) return json({}, 422);
        return json(
          {
            document_id: DOCUMENT,
            sha256: SHA256,
            action: "approve",
            approved_at: "2026-10-16T00:00:00+00:00",
            approved_by: "reviewer",
          },
          201,
        );
      }
      return undefined;
    });
  }

  it("registers the confirmation for the uploaded file in the real-AI build", async () => {
    vi.stubEnv("VITE_REVIEW_MODE", "dec007-real-qwen");
    const calls = servingAuthorization();
    const user = userEvent.setup();
    renderPage();

    await user.click(
      await screen.findByRole("button", { name: "登记外发授权" }),
    );
    // The declaration, the full hash and the server-validated confirmation are on screen.
    expect(screen.getByText(SHA256)).toBeTruthy();
    expect(screen.getByText(/我确认我依法有权处理该文件/)).toBeTruthy();
    const submit = screen.getByRole("button", { name: "确认授权该文件" });
    expect(submit).toHaveProperty("disabled", true);

    await user.click(screen.getByLabelText(/我已阅读并同意上述声明/));
    await user.type(
      screen.getByLabelText(/授权理由/),
      "面试演示合成样本，确认有权处理",
    );
    await user.click(screen.getByRole("button", { name: "确认授权该文件" }));

    await waitFor(() =>
      expect(
        calls.filter((call) => call.path.endsWith("/external-authorization"))
          .length,
      ).toBe(1),
    );
    const authorization = calls.find((call) =>
      call.path.endsWith("/external-authorization"),
    );
    expect(authorization?.authorization).toBe("Bearer test-token");
    expect(authorization?.body).toEqual({
      reason: "面试演示合成样本，确认有权处理",
      confirmed: true,
    });
    expect(await screen.findByText(/已登记外发授权/)).toBeTruthy();
  });

  it("never shows the control in a build that has no external authorization", async () => {
    servingAuthorization();
    renderPage();
    await screen.findByText(/只能选择服务端状态为“可用于审查”的文档/);
    expect(screen.queryByRole("button", { name: "登记外发授权" })).toBeNull();
  });

  it("explains a refused review as a missing per-file confirmation", async () => {
    vi.stubEnv("VITE_REVIEW_MODE", "dec007-real-qwen");
    servingPage((call) => {
      if (call.method === "GET" && call.path === `/api/v1/projects/${PROJECT}`)
        return json(projectPayload());
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/documents?`)
      )
        return json({
          items: [documentPayload({ status: "ready", issues: [] })],
          offset: 0,
          limit: 100,
          total: 1,
        });
      if (
        call.method === "GET" &&
        call.path.startsWith(`/api/v1/projects/${PROJECT}/reviews?`)
      )
        return json({ items: [], offset: 0, limit: 50, total: 0 });
      if (
        call.method === "GET" &&
        call.path === `/api/v1/projects/${PROJECT}/versions`
      )
        return json({ items: [] });
      if (
        call.method === "POST" &&
        call.path === `/api/v1/projects/${PROJECT}/reviews`
      )
        return json(
          { code: "FORBIDDEN", message: "hidden", request_id: "req-1" },
          403,
        );
      return undefined;
    });
    const user = userEvent.setup();
    renderPage();
    await user.click(
      await screen.findByLabelText(`选择文档 ${DOCUMENT} 开始审查`),
    );
    await user.click(screen.getByRole("button", { name: "发起审查" }));
    expect(
      await screen.findByText(/真实模型部署还要求所选文件已逐个登记外发授权/),
    ).toBeTruthy();
  });
});
