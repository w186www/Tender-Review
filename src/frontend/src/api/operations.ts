import { client, unwrap } from "./client";
import type { components } from "./schema";

export type Identity = components["schemas"]["Identity"];
export type Project = components["schemas"]["Project"];
export type ProjectCreate = components["schemas"]["ProjectCreate"];
export type ProjectUpdate = components["schemas"]["ProjectUpdate"];
export type DocumentRecord = components["schemas"]["Document"];
export type ReviewTask = components["schemas"]["ReviewTask"];
export type RiskFinding = components["schemas"]["RiskFinding"];
export type CitationLocation = components["schemas"]["CitationLocation"];
export type ReportMetadata = components["schemas"]["ReportMetadata"];
export type AuditEvent = components["schemas"]["AuditEvent"];
export type ReadRequestOptions = { signal?: AbortSignal };

export const api = {
  async login(tenant_id: string, username: string, password: string) {
    return unwrap(
      client.POST("/auth/token", { body: { tenant_id, username, password } }),
    );
  },
  async identity(options?: ReadRequestOptions) {
    return unwrap(client.GET("/auth/me", { signal: options?.signal }));
  },
  async logout() {
    return unwrap(client.POST("/auth/logout"));
  },
  async projects(offset = 0, limit = 20, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/projects", {
        params: { query: { offset, limit } },
        signal: options?.signal,
      }),
    );
  },
  async project(projectId: string, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/projects/{projectId}", {
        params: { path: { projectId } },
        signal: options?.signal,
      }),
    );
  },
  async projectVersions(projectId: string, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/projects/{projectId}/versions", {
        params: { path: { projectId } },
        signal: options?.signal,
      }),
    );
  },
  async createProject(body: ProjectCreate, key: string) {
    return unwrap(
      client.POST("/projects", {
        params: { header: { "Idempotency-Key": key } },
        body,
      }),
    );
  },
  async updateProject(projectId: string, body: ProjectUpdate) {
    return unwrap(
      client.PUT("/projects/{projectId}", {
        params: { path: { projectId } },
        body,
      }),
    );
  },
  async documents(
    projectId: string,
    offset = 0,
    limit = 50,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/documents", {
        params: { path: { projectId }, query: { offset, limit } },
        signal: options?.signal,
      }),
    );
  },
  async document(
    projectId: string,
    documentId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/documents/{documentId}", {
        params: { path: { projectId, documentId } },
        signal: options?.signal,
      }),
    );
  },
  async upload(projectId: string, file: File, key: string) {
    return unwrap(
      client.POST("/projects/{projectId}/documents", {
        params: { path: { projectId }, header: { "Idempotency-Key": key } },
        body: { file: file as unknown as string },
        bodySerializer(body) {
          const form = new FormData();
          form.set("file", body.file as unknown as Blob);
          return form;
        },
      }),
    );
  },
  async documentContext(
    projectId: string,
    documentId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/documents/{documentId}/context", {
        params: { path: { projectId, documentId } },
        signal: options?.signal,
      }),
    );
  },
  async confirmDocumentContext(
    projectId: string,
    documentId: string,
    body: components["schemas"]["ContextConfirmation"],
  ) {
    return unwrap(
      client.POST("/projects/{projectId}/documents/{documentId}/context", {
        params: { path: { projectId, documentId } },
        body,
      }),
    );
  },
  async reviews(
    projectId: string,
    offset = 0,
    limit = 20,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/reviews", {
        params: { path: { projectId }, query: { offset, limit } },
        signal: options?.signal,
      }),
    );
  },
  async createReview(projectId: string, document_ids: string[], key: string) {
    return unwrap(
      client.POST("/projects/{projectId}/reviews", {
        params: { path: { projectId }, header: { "Idempotency-Key": key } },
        body: { document_ids },
      }),
    );
  },
  async review(reviewTaskId: string, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/reviews/{reviewTaskId}", {
        params: { path: { reviewTaskId } },
        signal: options?.signal,
      }),
    );
  },
  async pendingReviews(offset = 0, limit = 50, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/review-tasks/pending", {
        params: { query: { offset, limit } },
        signal: options?.signal,
      }),
    );
  },
  async findings(
    reviewTaskId: string,
    runId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/review-tasks/{reviewTaskId}/runs/{runId}/findings", {
        params: { path: { reviewTaskId, runId } },
        signal: options?.signal,
      }),
    );
  },
  async citations(
    reviewTaskId: string,
    runId: string,
    findingId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET(
        "/review-tasks/{reviewTaskId}/runs/{runId}/findings/{findingId}/citations",
        {
          params: { path: { reviewTaskId, runId, findingId } },
          signal: options?.signal,
        },
      ),
    );
  },
  async reviewHistory(
    reviewTaskId: string,
    runId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/review-tasks/{reviewTaskId}/runs/{runId}/history", {
        params: { path: { reviewTaskId, runId } },
        signal: options?.signal,
      }),
    );
  },
  async decide(
    reviewTaskId: string,
    runId: string,
    findingId: string,
    body: components["schemas"]["ReviewDecisionRequest"],
    key: string,
  ) {
    return unwrap(
      client.POST(
        "/review-tasks/{reviewTaskId}/runs/{runId}/findings/{findingId}/decisions",
        {
          params: {
            path: { reviewTaskId, runId, findingId },
            header: { "Idempotency-Key": key },
          },
          body,
        },
      ),
    );
  },
  async publish(reviewTaskId: string, runId: string) {
    return unwrap(
      client.POST("/review-tasks/{reviewTaskId}/runs/{runId}/publish", {
        params: { path: { reviewTaskId, runId } },
      }),
    );
  },
  async resume(reviewTaskId: string, runId: string) {
    return unwrap(
      client.POST("/review-tasks/{reviewTaskId}/runs/{runId}/resume", {
        params: { path: { reviewTaskId, runId } },
      }),
    );
  },
  async retryReview(reviewTaskId: string, runId: string) {
    return unwrap(
      client.POST("/review-tasks/{reviewTaskId}/runs/{runId}/retry", {
        params: { path: { reviewTaskId, runId } },
      }),
    );
  },
  async reports(resultId: string, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/review-results/{resultId}/reports", {
        params: { path: { resultId } },
        signal: options?.signal,
      }),
    );
  },
  async createReport(resultId: string, format: "docx" | "pdf", key: string) {
    return unwrap(
      client.POST("/review-results/{resultId}/reports/{outputFormat}", {
        params: {
          path: { resultId, outputFormat: format },
          header: { "Idempotency-Key": key },
        },
      }),
    );
  },
  async downloadReport(reportId: string, options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/reports/{reportId}/content", {
        params: { path: { reportId } },
        parseAs: "blob",
        signal: options?.signal,
      }),
    );
  },
  async originalDocument(
    projectId: string,
    documentId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/documents/{documentId}/original", {
        params: { path: { projectId, documentId } },
        parseAs: "blob",
        signal: options?.signal,
      }),
    );
  },
  async auditEvents(
    query: {
      resource_id?: string;
      actor_id?: string;
      action?: string;
      from?: string;
      to?: string;
      offset?: number;
      limit?: number;
    },
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/audit/events", {
        params: { query },
        signal: options?.signal,
      }),
    );
  },
};
