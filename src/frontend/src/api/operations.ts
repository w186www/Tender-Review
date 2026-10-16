import { client, postJson, unwrap } from "./client";
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
export type ConfigurationCatalog =
  components["schemas"]["ConfigurationCatalog"];
export type ConfigurationState =
  components["schemas"]["ConfigurationStateResponse"];
export type LegalManagement = components["schemas"]["LegalManagementResponse"];
export type ReadRequestOptions = { signal?: AbortSignal };

export type ExternalAuthorizationRecord = {
  document_id: string;
  sha256: string;
  action: "approve";
  approved_at: string;
  approved_by: string;
};

export type ExternalAuthorizationRequest = {
  reason: string;
  confirmed: true;
};

/**
 * The reviewer's explicit, per-file confirmation that one uploaded document may be sent
 * to the external model service. The route is served by the API but deliberately absent
 * from this round's frozen OpenAPI contract (`contracts/**` is not modified), so it is
 * called through the client's explicit authenticated JSON helper instead of the generated
 * client. The server resolves the file SHA-256 itself and accepts no hash from here.
 */
export async function authorizeDocumentExternalProcessing(
  projectId: string,
  documentId: string,
  body: ExternalAuthorizationRequest,
): Promise<ExternalAuthorizationRecord> {
  return postJson<ExternalAuthorizationRecord>(
    `/api/v1/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/external-authorization`,
    body,
  );
}

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
  /**
   * The parsed fragments of one document: the automatic text a parser produced and the
   * effective text (which a recorded human correction may have replaced). A document whose
   * quality gate failed is only repairable through these fragments.
   */
  async documentSections(
    projectId: string,
    documentId: string,
    options?: ReadRequestOptions,
  ) {
    return unwrap(
      client.GET("/projects/{projectId}/documents/{documentId}/sections", {
        params: { path: { projectId, documentId } },
        signal: options?.signal,
      }),
    );
  },
  /**
   * Record one human text correction. The server re-runs the quality gate on the corrected
   * fragments itself: this call can never assert that a document is good enough.
   */
  async correctDocumentText(
    projectId: string,
    documentId: string,
    body: components["schemas"]["QualityCorrection"],
  ) {
    return unwrap(
      client.POST("/projects/{projectId}/documents/{documentId}/corrections", {
        params: { path: { projectId, documentId } },
        body,
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
  async configurationCatalog(options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/admin/configurations/catalog", { signal: options?.signal }),
    );
  },
  async configurations(options?: ReadRequestOptions) {
    return unwrap(
      client.GET("/admin/configurations", { signal: options?.signal }),
    );
  },
  async createConfigurationDraft(
    body: components["schemas"]["ConfigurationDraftRequest"],
  ) {
    return unwrap(client.POST("/admin/configurations/drafts", { body }));
  },
  async publishConfiguration(
    body: components["schemas"]["ConfigurationPublishRequest"],
  ) {
    return unwrap(client.POST("/admin/configurations/publish", { body }));
  },
  async deactivateConfiguration(
    body: components["schemas"]["ConfigurationDisableRequest"],
  ) {
    return unwrap(client.POST("/admin/configurations/deactivate", { body }));
  },
  async rollbackConfiguration(
    body: components["schemas"]["ConfigurationRollbackRequest"],
  ) {
    return unwrap(client.POST("/admin/configurations/rollback", { body }));
  },
  async legalManagement(options?: ReadRequestOptions) {
    return unwrap(client.GET("/admin/legal", { signal: options?.signal }));
  },
  async createLegalDraft(body: components["schemas"]["LegalDraftRequest"]) {
    return unwrap(client.POST("/admin/legal/drafts", { body }));
  },
  async changeLegalPublication(
    body: components["schemas"]["PublicationRequest"],
  ) {
    return unwrap(client.POST("/admin/legal/publications", { body }));
  },
};
