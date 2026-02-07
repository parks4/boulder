import { useCallback, useState, useEffect } from "react";
import { cn } from "@/lib/cn";
import { useConfigStore } from "@/stores/configStore";
import { useSimulationStore } from "@/stores/simulationStore";
import { startSimulation } from "@/api/simulations";
import { fetchMechanisms } from "@/api/mechanisms";
import { toast } from "sonner";

export function SimulateCard() {
  const config = useConfigStore((s) => s.config);
  const { isRunning, startSimulation: setStarted } = useSimulationStore();
  const [mechanisms, setMechanisms] = useState<{ label: string; value: string }[]>([]);
  const [selectedMechanism, setSelectedMechanism] = useState("gri30.yaml");
  const [simTime, setSimTime] = useState("10");
  const [timeStep, setTimeStep] = useState("1");

  useEffect(() => {
    fetchMechanisms()
      .then(setMechanisms)
      .catch(() => {
        /* use default */
      });
  }, []);

  const handleRun = useCallback(async () => {
    if (config.nodes.length === 0) {
      toast.error("Add at least one reactor before simulating");
      return;
    }
    try {
      const resp = await startSimulation(
        config,
        selectedMechanism,
        parseFloat(simTime),
        parseFloat(timeStep),
      );
      setStarted(resp.simulation_id);
      toast.success("Simulation started");
    } catch (err) {
      toast.error(`Failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  }, [config, selectedMechanism, simTime, timeStep, setStarted]);

  return (
    <div className="rounded-lg border border-border bg-card p-4 space-y-3">
      <h3 className="font-semibold text-sm text-foreground">Simulate</h3>

      <div className="space-y-2">
        <label className="block text-xs text-muted-foreground">
          Mechanism
          <select
            value={selectedMechanism}
            onChange={(e) => setSelectedMechanism(e.target.value)}
            className="block w-full mt-1 px-2 py-1.5 text-sm rounded-md bg-input text-foreground border border-border"
          >
            {mechanisms.length === 0 && (
              <option value="gri30.yaml">gri30.yaml</option>
            )}
            {mechanisms.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </select>
        </label>

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

      <button
        id="run-simulation"
        onClick={handleRun}
        disabled={isRunning || config.nodes.length === 0}
        className={cn(
          "w-full px-3 py-2 text-sm rounded-md font-medium transition-opacity",
          isRunning
            ? "bg-muted text-muted-foreground cursor-not-allowed"
            : "bg-success text-white hover:opacity-90",
        )}
      >
        {isRunning ? "Running..." : "Run Simulation (Ctrl+Enter)"}
      </button>
    </div>
  );
}
