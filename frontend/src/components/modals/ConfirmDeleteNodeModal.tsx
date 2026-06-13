import { Button } from "@/components/ui/Button";

interface Props {
  open: boolean;
  nodeId: string;
  nodeType: string;
  onClose: () => void;
  onConfirm: () => void;
}

export function ConfirmDeleteNodeModal({
  open,
  nodeId,
  nodeType,
  onClose,
  onConfirm,
}: Props) {
  if (!open) return null;

  return (
    <div
      id="confirm-delete-node-modal"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="w-full max-w-md bg-card border border-border rounded-lg shadow-lg p-6 space-y-4">
        <h2 className="text-lg font-semibold text-foreground">Delete node?</h2>
        <p className="text-sm text-muted-foreground">
          Delete <span className="font-mono text-foreground">{nodeId}</span>
          {nodeType ? (
            <>
              {" "}
              (<span className="text-foreground">{nodeType}</span>)
            </>
          ) : null}
          ? Connected flow devices will also be removed. This cannot be undone.
        </p>
        <div className="flex justify-end gap-2 pt-2">
          <Button id="cancel-delete-node" onClick={onClose} variant="secondary" size="sm">
            Cancel
          </Button>
          <Button id="confirm-delete-node" onClick={onConfirm} variant="destructive" size="sm">
            Delete
          </Button>
        </div>
      </div>
    </div>
  );
}
