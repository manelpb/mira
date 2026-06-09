import { useState, type ComponentProps } from "react"

import { Button } from "@/components/ui/button"
import { ConfirmDialog } from "@/components/ui/confirm-dialog"

/**
 * A button that asks for confirmation before running its action. Drop it in
 * anywhere a destructive/irreversible click needs a guard — it owns the dialog
 * open + in-flight state itself, so callers only provide `onConfirm` and the
 * dialog copy. Button appearance props (variant, size, className, children,
 * title, disabled…) pass straight through to the underlying Button.
 */
export function ConfirmButton({
  onConfirm,
  dialogTitle,
  dialogDescription,
  confirmLabel = "Confirm",
  cancelLabel = "Cancel",
  destructive = false,
  children,
  ...buttonProps
}: {
  onConfirm: () => void | Promise<void>
  dialogTitle: string
  dialogDescription?: string
  confirmLabel?: string
  cancelLabel?: string
  destructive?: boolean
} & ComponentProps<typeof Button>) {
  const [open, setOpen] = useState(false)
  const [loading, setLoading] = useState(false)

  const handleConfirm = async () => {
    setLoading(true)
    try {
      await onConfirm()
      setOpen(false)
    } finally {
      setLoading(false)
    }
  }

  return (
    <>
      <Button
        type="button"
        {...buttonProps}
        onClick={(e) => {
          // Don't let the click bubble to a clickable row/card behind it.
          e.stopPropagation()
          setOpen(true)
        }}
      >
        {children}
      </Button>
      <ConfirmDialog
        open={open}
        onOpenChange={setOpen}
        title={dialogTitle}
        description={dialogDescription}
        confirmLabel={confirmLabel}
        cancelLabel={cancelLabel}
        destructive={destructive}
        loading={loading}
        onConfirm={handleConfirm}
      />
    </>
  )
}
