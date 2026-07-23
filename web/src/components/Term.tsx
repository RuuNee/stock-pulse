import { useState, type ReactNode } from "react";
import { TERMS } from "../lib/terms";

// Dotted-underline term that reveals a plain-language popover on tap/hover.
export default function Term({ k, children }: { k: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const entry = TERMS[k];
  if (!entry) return <>{children}</>;

  return (
    <span className="relative inline-block">
      <span
        className="term"
        tabIndex={0}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((o) => !o);
        }}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onBlur={() => setOpen(false)}
      >
        {children}
      </span>
      {open && (
        <span
          className="absolute z-30 left-0 top-full mt-1 w-64 max-w-[80vw] p-3 rounded-xl text-sm shadow-lg block"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text)" }}
          onClick={(e) => e.stopPropagation()}
        >
          <b className="block mb-1">{entry.title}</b>
          <span style={{ color: "var(--muted)" }}>{entry.short}</span>
          {entry.more && (
            <span className="block mt-1.5" style={{ color: "var(--muted)" }}>
              {entry.more}
            </span>
          )}
        </span>
      )}
    </span>
  );
}
