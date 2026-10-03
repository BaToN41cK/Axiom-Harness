import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { copyText } from "../lib/format";
import { useLocale } from "../lib/locale";

interface Props {
  code: string;
  language?: string;
}

/** Fenced code block with a real copy action and the detected language. */
export default function CodeBlock({ code, language }: Props) {
  const [copied, setCopied] = useState(false);
  const { t } = useLocale();

  const copy = async () => {
    const ok = await copyText(code);
    if (!ok) return;
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <div className="code-block">
      <div className="code-head">
        <span className="code-lang">{language || "text"}</span>
        <button className="code-copy" onClick={copy} title={t("ui.code.copy_code")}>
          {copied ? <Check size={12} strokeWidth={2.2} /> : <Copy size={12} strokeWidth={1.9} />}
          <span>{copied ? t("ui.code.copied") : t("ui.code.copy")}</span>
        </button>
      </div>
      <pre>
        <code>{code}</code>
      </pre>
    </div>
  );
}

/** Small icon-only copy button (used for whole answers). */
export function CopyIconButton({
  text,
  title,
  className = "",
}: {
  text: string;
  title?: string;
  className?: string;
}) {
  const [copied, setCopied] = useState(false);
  const { t } = useLocale();
  const label = title ?? t("ui.code.copy");
  return (
    <button
      className={"msg-action " + className}
      title={copied ? t("ui.code.copied") : label}
      onClick={async () => {
        if (await copyText(text)) {
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1400);
        }
      }}
    >
      {copied ? <Check size={13} strokeWidth={2.2} /> : <Copy size={13} strokeWidth={1.9} />}
      <span>{copied ? t("ui.code.copied") : label}</span>
    </button>
  );
}