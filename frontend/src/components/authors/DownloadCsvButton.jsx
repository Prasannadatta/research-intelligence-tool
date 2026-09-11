import { useCallback, useState } from "react";
import { Alert, Box, Button, CircularProgress, Typography } from "@mui/material";
import FileDownloadRoundedIcon from "@mui/icons-material/FileDownloadRounded";

/**
 * Trigger a browser download from a Blob, then clean up the temporary URL/DOM node.
 */
export function downloadBlobFile(blob, filename) {
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = blobUrl;
  link.download = filename || "export.csv";
  link.style.display = "none";
  document.body.appendChild(link);
  try {
    link.click();
  } finally {
    link.remove();
    URL.revokeObjectURL(blobUrl);
  }
}

/**
 * Parse Content-Disposition filename when the backend provides one.
 */
export function filenameFromContentDisposition(headerValue, fallback) {
  if (!headerValue) {
    return fallback;
  }
  const utfMatch = /filename\*=UTF-8''([^;]+)/i.exec(headerValue);
  if (utfMatch?.[1]) {
    try {
      return decodeURIComponent(utfMatch[1].trim().replace(/^"|"$/g, ""));
    } catch {
      return utfMatch[1].trim().replace(/^"|"$/g, "");
    }
  }
  const plainMatch = /filename="?([^";]+)"?/i.exec(headerValue);
  if (plainMatch?.[1]) {
    return plainMatch[1].trim();
  }
  return fallback;
}

export async function downloadCsvFromResponse(response, fallbackFilename) {
  const header =
    response?.headers?.["content-disposition"] ||
    response?.headers?.["Content-Disposition"];
  const filename = filenameFromContentDisposition(header, fallbackFilename);
  const blob = response?.data instanceof Blob ? response.data : new Blob([response?.data]);
  downloadBlobFile(blob, filename);
  return filename;
}

/**
 * Shared Download CSV control for author and grant publication pages.
 */
export default function DownloadCsvButton({
  disabled = false,
  onExport,
  helperText = "Exports all filtered publications with available author, institution, grant, venue, and source metadata.",
  compact = false,
  sx = undefined,
}) {
  const [exporting, setExporting] = useState(false);
  const [error, setError] = useState(null);

  const handleClick = useCallback(async () => {
    if (exporting || disabled || typeof onExport !== "function") {
      return;
    }
    setExporting(true);
    setError(null);
    try {
      await onExport();
    } catch (err) {
      let message =
        err?.response?.data?.detail ||
        err?.message ||
        "Failed to prepare CSV export.";

      const data = err?.response?.data;
      if (data instanceof Blob) {
        try {
          const text = await data.text();
          const parsed = JSON.parse(text);
          message = parsed?.detail || message;
        } catch {
          message = "Failed to prepare CSV export.";
        }
      }

      setError(typeof message === "string" ? message : "Failed to prepare CSV export.");
    } finally {
      setExporting(false);
    }
  }, [disabled, exporting, onExport]);

  return (
    <Box sx={compact ? { display: "inline-flex", flexDirection: "column", ...sx } : { mt: 2, mb: 1, ...sx }}>
      <Button
        variant="outlined"
        color="inherit"
        size="small"
        disableElevation
        startIcon={
          exporting ? (
            <CircularProgress size={16} color="inherit" />
          ) : (
            <FileDownloadRoundedIcon fontSize="small" />
          )
        }
        onClick={handleClick}
        disabled={disabled || exporting}
        data-testid="download-csv-button"
        sx={{ textTransform: "none", whiteSpace: "nowrap" }}
      >
        {exporting ? "Preparing CSV…" : "Download CSV"}
      </Button>
      {!compact && helperText ? (
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ display: "block", mt: 0.75, lineHeight: 1.4 }}
        >
          {helperText}
        </Typography>
      ) : null}
      {error ? (
        <Alert
          severity="warning"
          variant="outlined"
          sx={{ mt: compact ? 1 : 1.5, maxWidth: compact ? 280 : "100%" }}
          onClose={() => setError(null)}
        >
          {error}
        </Alert>
      ) : null}
    </Box>
  );
}
