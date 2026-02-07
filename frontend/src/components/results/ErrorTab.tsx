interface Props {
  error: string | null;
}

export function ErrorTab({ error }: Props) {
  if (!error) {
    return <p className="text-sm text-muted-foreground">No errors.</p>;
  }

  return (
    <div
      id="simulation-error-display"
      className="rounded border border-destructive bg-destructive/10 p-4"
    >
      <h4 className="text-sm font-medium text-destructive mb-1">
        Simulation Error
      </h4>
      <pre className="text-xs text-destructive whitespace-pre-wrap">{error}</pre>
    </div>
  );
}
