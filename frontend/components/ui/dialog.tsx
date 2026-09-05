"use client";

import { useEffect, useId, useRef, type KeyboardEvent } from "react";
import { ActionButton } from "./form-controls";

const focusableSelector = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function trapDialogTab(event: KeyboardEvent<HTMLDialogElement>) {
  if (event.key !== "Tab") return;
  const dialog = event.currentTarget;
  const focusable = [...dialog.querySelectorAll<HTMLElement>(focusableSelector)].filter((element) => {
    const style = getComputedStyle(element);
    return style.display !== "none" && style.visibility !== "hidden";
  });
  if (!focusable.length) return;
  const first = focusable[0];
  const last = focusable.at(-1);
  if (!last) return;
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

export function Dialog({
  open,
  title,
  description,
  onClose,
  children,
}: {
  open: boolean;
  title: string;
  description?: string;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  const descriptionId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);
  return (
    <dialog className="dialog" ref={ref} onCancel={onClose} onClose={onClose} onKeyDown={trapDialogTab} aria-labelledby={titleId} aria-describedby={description ? descriptionId : undefined}>
      <div className="dialog-heading">
        <div>
          <p className="eyebrow">Chowly action</p>
          <h2 id={titleId}>{title}</h2>
        </div>
        <ActionButton tone="quiet" onClick={onClose} aria-label={`Close ${title}`}>Close</ActionButton>
      </div>
      {description && <p className="dialog-description" id={descriptionId}>{description}</p>}
      {children}
    </dialog>
  );
}
