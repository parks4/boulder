import type { SimulationResults } from "@/types/simulation";
import { useSimulationStore } from "@/stores/simulationStore";
import { exportConfig } from "@/api/configs";
import { useConfigStore } from "@/stores/configStore";
import { toast } from "sonner";

interface Props {
  results: SimulationResults;
}

export function SummaryTab({ results }: Props) {
  const pythonCode = useSimulationStore((s) => s.pythonCode);
  const config = useConfigStore((s) => s.config);

  const handleDownloadPy = () => {
    if (!pythonCode) return;
    const blob = new Blob([pythonCode], { type: "text/x-python" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "simulation.py";
    a.click();
    URL.revokeObjectURL(url);
    toast.success("Python code downloaded");
  };

  const handleDownloadYaml = async () => {
    try {
      const resp = await exportConfig(config);
      const blob = new Blob([resp.yaml], { type: "text/yaml" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = "config.yaml";
      a.click();
      URL.revokeObjectURL(url);
      toast.success("YAML config downloaded");
    } catch (err) {
      toast.error(`Download failed: ${err instanceof Error ? err.message : String(err)}`);
    }
  };

  return (
    <div className="space-y-4">
      {results.elapsed_time != null && (
        <p className="text-sm text-foreground">
          Elapsed time: <span className="font-mono">{results.elapsed_time.toFixed(2)}s</span>
        </p>
      )}

      {Array.isArray(results.summary) && results.summary.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <tbody>
              {results.summary.map((row, i) => (
                <tr key={i} className="border-b border-border">
                  {Object.entries(row as Record<string, unknown>).map(([k, v]) => (
                    <td key={k} className="px-2 py-1 text-xs text-foreground">
                      <span className="text-muted-foreground">{k}: </span>
                      {String(v)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="flex gap-2">
        <button
          onClick={handleDownloadPy}
          disabled={!pythonCode}
          className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80 disabled:opacity-50"
        >
          Download Python
        </button>
        <button
          onClick={handleDownloadYaml}
          className="px-3 py-1.5 text-sm rounded-md bg-secondary text-secondary-foreground hover:opacity-80"
        >
          Download YAML
        </button>
      </div>
    </div>
  );
}
