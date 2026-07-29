import { apiFetch } from "./client";

interface SpeciesColorsResponse {
  species_colors: Record<string, string>;
}

/** Species -> hex color palette a host plugin has registered, if any. */
export function fetchSpeciesColors(): Promise<Record<string, string>> {
  return apiFetch<SpeciesColorsResponse>("/ui/species-colors").then(
    (r) => r.species_colors,
  );
}
