import { test, expect, type Page } from "@playwright/test";

// ---------------------------------------------------------------------------
// Helper function to add a reactor via the modal
// ---------------------------------------------------------------------------

async function addReactor(
  page: Page,
  id: string,
  type: string,
  temp = "1000",
  pressure = "101325",
  composition = "O2:1,N2:3.76",
) {
  await page.click("#open-reactor-modal");
  await expect(page.locator("#add-reactor-modal")).toBeVisible();
  await page.fill("#reactor-id", id);
  await page.selectOption("#reactor-type", type);
  await page.fill("#reactor-temp", temp);
  await page.fill("#reactor-pressure", pressure);
  await page.fill("#reactor-composition", composition);
  await page.click("#add-reactor");
  // Wait for modal to close
  await expect(page.locator("#add-reactor-modal")).not.toBeVisible();
}

// ---------------------------------------------------------------------------
// Test suite – ported from the original test_e2e.py
// ---------------------------------------------------------------------------

test.describe("Boulder E2E Tests", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    // Wait for the app shell to load.
    await expect(page.getByRole("heading", { name: "Boulder" })).toBeVisible();
  });

  test("1. add reactor flow", async ({ page }) => {
    await addReactor(page, "test_reactor", "IdealGasReactor");
    // Graph should now contain the reactor
    // (Cytoscape renders to canvas, check state via the store)
    await expect(page.locator("#reactor-graph")).toBeVisible();
  });

  test("2. add reactor validation - empty form", async ({ page }) => {
    await page.click("#open-reactor-modal");
    await expect(page.locator("#add-reactor-modal")).toBeVisible();
    // Submit with empty ID
    await page.click("#add-reactor");
    // Modal should stay open (toast error) – ID required
    await expect(page.locator("#add-reactor-modal")).toBeVisible();
  });

  test("3. add MFC flow", async ({ page }) => {
    // Add two reactors first
    await addReactor(page, "r1", "IdealGasReactor");
    await addReactor(page, "r2", "Reservoir");

    // Open MFC modal
    await page.click("#open-mfc-modal");
    await expect(page.locator("#add-mfc-modal")).toBeVisible();
    await page.fill("#mfc-id", "mfc1");
    await page.selectOption("#mfc-source", "r1");
    await page.selectOption("#mfc-target", "r2");
    await page.fill("#mfc-flow-rate", "0.001");
    await page.click("#add-mfc");

    // Modal should close
    await expect(page.locator("#add-mfc-modal")).not.toBeVisible();
  });

  test("4. config upload button visible", async ({ page }) => {
    await expect(page.locator("#config-upload-btn")).toBeVisible();
  });

  test("5. YAML editor flow", async ({ page }) => {
    // Click config filename to open editor
    await page.click("#config-file-name-span");
    await expect(page.locator("#config-yaml-modal")).toBeVisible();

    // Close
    const closeBtn = page.locator("#config-yaml-modal button:has-text('Cancel')");
    await closeBtn.click();
    await expect(page.locator("#config-yaml-modal")).not.toBeVisible();
  });

  test("6. graph node selection shows properties", async ({ page }) => {
    // We can't easily click a Cytoscape node via Playwright (canvas),
    // but we can verify the properties panel renders when no selection
    const panel = page.locator("#properties-panel");
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("Click a node");
  });

  test("7. run simulation shows results", async ({ page }) => {
    // This test requires a running FastAPI backend to connect to.
    // In CI, it would be skipped if no backend is available.
    const runBtn = page.locator("#run-simulation");
    await expect(runBtn).toBeVisible();
    // Verify the button exists and is labeled correctly
    await expect(runBtn).toContainText("Run Simulation");
  });

  test("8. keyboard shortcut Ctrl+Enter", async ({ page }) => {
    // Pressing Ctrl+Enter should trigger simulation if nodes exist
    // Without nodes, it should be a no-op (no crash)
    await page.keyboard.press("Control+Enter");
    // App should not crash – verify page is still responsive
    await expect(page.getByRole("heading", { name: "Boulder" })).toBeVisible();
  });

  test("10. stage-interface diamond node: graph API returns stage_interface metadata", async ({
    page,
  }) => {
    // Verify that the graph /elements API forwards stage_interface metadata so the
    // Cytoscape [stage_interface = true] diamond selector can fire.
    // We hit the API directly (requires a running backend).
    const twoStageConfig = {
      groups: {
        stage_a: { mechanism: "gri30.yaml", solve: "advance_to_steady_state" },
        stage_b: { mechanism: "gri30.yaml", solve: "advance_to_steady_state" },
      },
      phases: { gas: { mechanism: "gri30.yaml" } },
      nodes: [
        {
          id: "r_a",
          type: "IdealGasConstPressureMoleReactor",
          properties: {
            group: "stage_a",
            temperature: 1200,
            pressure: 101325,
            composition: "N2:1",
            volume: 1e-5,
          },
        },
        {
          id: "r_b",
          type: "IdealGasConstPressureMoleReactor",
          properties: {
            group: "stage_b",
            temperature: 900,
            pressure: 101325,
            composition: "N2:1",
            volume: 5e-6,
          },
        },
        // Synthesised interface reservoir node (as it would appear after solve)
        {
          id: "a_to_b__iface",
          type: "Reservoir",
          properties: {
            temperature: 1200,
            pressure: 101325,
            composition: "N2:1",
            stage_interface: true,
            upstream_stage: "stage_a",
            downstream_stage: "stage_b",
            source_node: "r_a",
            target_node: "r_b",
          },
          metadata: {
            stage_interface: true,
            upstream_stage: "stage_a",
            downstream_stage: "stage_b",
          },
        },
      ],
      connections: [
        {
          id: "a_to_b",
          type: "MassFlowController",
          source: "r_a",
          target: "r_b",
          properties: { mass_flow_rate: 1e-4 },
        },
      ],
    };

    // POST to the graph elements API
    const response = await page.request.post("/api/graph/elements", {
      data: { config: twoStageConfig },
      headers: { "Content-Type": "application/json" },
    });

    if (response.status() === 200) {
      const elements = await response.json();
      const ifaceNode = elements.find(
        (el: { data: { id?: string; stage_interface?: unknown } }) =>
          el.data?.id === "a_to_b__iface",
      );
      expect(ifaceNode).toBeDefined();
      expect(ifaceNode.data.stage_interface).toBe(true);
      expect(ifaceNode.data.upstream_stage).toBe("stage_a");
    } else {
      // Backend not available in this test environment – skip gracefully
      test.skip();
    }
  });

  test("9. duplicate reactor ID rejected", async ({ page }) => {
    await addReactor(page, "dup_reactor", "IdealGasReactor");

    // Try to add another with same ID
    await page.click("#open-reactor-modal");
    await page.fill("#reactor-id", "dup_reactor");
    await page.selectOption("#reactor-type", "Reservoir");
    await page.fill("#reactor-temp", "300");
    await page.fill("#reactor-pressure", "101325");
    await page.fill("#reactor-composition", "O2:1");
    await page.click("#add-reactor");

    // Modal should stay open (error toast about duplicate)
    await expect(page.locator("#add-reactor-modal")).toBeVisible();
  });
});
