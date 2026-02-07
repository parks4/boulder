import { useCallback, useState } from "react";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { startSimulation } from "@/api/simulations";
import { Button } from "@/components/ui/Button";
import { toast } from "sonner";

export function SimulateCard() {
  const config = useConfigStore((s) => s.config);
  const { isRunning, startSimulation: setStarted } = useSimulationStore();
  const [simTime, setSimTime] = useState("10");
  const [timeStep, setTimeStep] = useState("1");

  const handleRun = useCallback(async () => {
    if (config.nodes.length === 0) {
      toast.error("Add at least one reactor before simulating");
      return;
    }
    try {
      const resp = await startSimulation(
        config,
        parseFloat(simTime),
        parseFloat(timeStep),
      );
      setStarted(resp.simulation_id);
      toast.success("Simulation started");
    } catch (err) {
      toast.error(`Failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [config, simTime, timeStep, setStarted]);

  const runDisabled = isRunning || config.nodes.length === 0;
  const runVariant = runDisabled ? "muted" : "success";

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Simulate</h3>

      <div className="space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <label className="block text-xs text-muted-foreground">
            Time (s)
            <input
              type="number"
              value={simTime}
              onChange={(e) => setSimTime(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
              min="0.1"
              step="0.1"
            />
          </label>
          <label className="block text-xs text-muted-foreground">
            Step (s)
            <input
              type="number"
              value={timeStep}
              onChange={(e) => setTimeStep(e.target.value)}
              className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
              min="0.01"
              step="0.01"
            />
          </label>
        </div>
      </div>

      <Button
        id="run-simulation"
        onClick={handleRun}
        disabled={runDisabled}
        variant={runVariant}
        className="w-full"
      >
        {isRunning ? "Running..." : "Run Simulation (Ctrl+Enter)"}
      </Button>
    </div>
  );
}
