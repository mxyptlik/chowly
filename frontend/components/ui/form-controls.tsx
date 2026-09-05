"use client";

import { forwardRef, useId, type ButtonHTMLAttributes, type InputHTMLAttributes, type SelectHTMLAttributes, type TextareaHTMLAttributes } from "react";
import { fieldAccessibility } from "./form-policy";

export { fieldAccessibility } from "./form-policy";

type FieldProps = {
  label: string;
  hint?: string;
  error?: string;
  optional?: boolean;
  children: (field: { id: string; describedBy?: string; invalid: boolean }) => React.ReactNode;
};

export function Field({ label, hint, error, optional, children }: FieldProps) {
  const id = useId();
  const accessibility = fieldAccessibility(id, hint, error);
  return (
    <div className={`field ${error ? "field-error" : ""}`}>
      <label className="field-label" htmlFor={id}>
        {label} {optional && <span className="field-optional">Optional</span>}
      </label>
      {children(accessibility)}
      {hint && <p className="field-hint" id={`${id}-hint`}>{hint}</p>}
      {error && <p className="field-message" id={`${id}-error`} role="alert">{error}</p>}
    </div>
  );
}

export const TextInput = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(function TextInput(props, ref) {
  return <input className={`control ${props.className ?? ""}`} ref={ref} {...props} />;
});

export const TextArea = forwardRef<HTMLTextAreaElement, TextareaHTMLAttributes<HTMLTextAreaElement>>(function TextArea(props, ref) {
  return <textarea className={`control control-area ${props.className ?? ""}`} ref={ref} {...props} />;
});

export const SelectInput = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(function SelectInput(props, ref) {
  return <select className={`control control-select ${props.className ?? ""}`} ref={ref} {...props} />;
});

export function FieldInput({ label, hint, error, optional, ...props }: InputHTMLAttributes<HTMLInputElement> & Omit<FieldProps, "children">) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional}>
      {({ id, describedBy, invalid }) => (
        <TextInput {...props} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      )}
    </Field>
  );
}

export function FieldTextArea({ label, hint, error, optional, ...props }: TextareaHTMLAttributes<HTMLTextAreaElement> & Omit<FieldProps, "children">) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional}>
      {({ id, describedBy, invalid }) => (
        <TextArea {...props} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      )}
    </Field>
  );
}

export function FieldSelect({ label, hint, error, optional, ...props }: SelectHTMLAttributes<HTMLSelectElement> & Omit<FieldProps, "children">) {
  return (
    <Field label={label} hint={hint} error={error} optional={optional}>
      {({ id, describedBy, invalid }) => (
        <SelectInput {...props} id={id} aria-describedby={describedBy} aria-invalid={invalid || undefined} />
      )}
    </Field>
  );
}

type ActionButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  pending?: boolean;
  pendingLabel?: string;
  tone?: "ink" | "sun" | "quiet" | "danger";
};

export function ActionButton({ pending, pendingLabel = "Working…", tone = "ink", children, disabled, ...props }: ActionButtonProps) {
  return (
    <button
      {...props}
      className={`action action-${tone} ${props.className ?? ""}`}
      disabled={disabled || pending}
      aria-disabled={disabled || pending || undefined}
      aria-busy={pending || undefined}
    >
      {pending && <span className="action-spinner" aria-hidden="true" />}
      <span>{pending ? pendingLabel : children}</span>
    </button>
  );
}
