import { apiFetch } from "./client";
import type { NormalizedConfig } from "@/types/config";

interface DefaultConfigResponse {
  config: NormalizedConfig;
  yaml: string;
}

interface PreloadedConfigResponse {
  preloaded: boolean;
  config?: NormalizedConfig;
  yaml?: string;
  filename?: string;
}

interface ParseResponse {
  config: NormalizedConfig;
  yaml: string;
}

interface ValidateResponse {
  config: NormalizedConfig;
}

interface ExportResponse {
  yaml: string;
}

interface UploadResponse {
  config: NormalizedConfig;
  yaml: string;
  filename: string;
}

export function fetchDefaultConfig() {
  return apiFetch<DefaultConfigResponse>("/configs/default");
}

export function fetchPreloadedConfig() {
  return apiFetch<PreloadedConfigResponse>("/configs/preloaded");
}

export function parseYaml(yaml: string) {
  return apiFetch<ParseResponse>("/configs/parse", {
    method: "POST",
    body: JSON.stringify({ yaml }),
  });
}

export function validateConfig(config: NormalizedConfig) {
  return apiFetch<ValidateResponse>("/configs/validate", {
    method: "POST",
    body: JSON.stringify({ config }),
  });
}

export function exportConfig(config: NormalizedConfig) {
  return apiFetch<ExportResponse>("/configs/export", {
    method: "POST",
    body: JSON.stringify({ config }),
  });
}

export async function uploadConfigFile(file: File): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", file);
  const res = await fetch("/api/configs/upload", {
    method: "POST",
    body: formData,
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`Upload failed: ${body}`);
  }
  return res.json();
}
