import { Button, Dialog, DialogContent, DialogTitle } from "@mui/material";

function InsightsViewAllDialog({
  open,
  onClose,
  title,
  children,
  maxWidth = "lg",
  paperSx,
  contentSx,
  "data-testid": testId,
}) {
  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth={maxWidth}
      fullWidth
      scroll="paper"
      data-testid={testId}
      PaperProps={{
        sx: paperSx,
      }}
    >
      <DialogTitle
        sx={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 2,
          fontSize: "1.1rem",
          fontWeight: 700,
          pr: 2,
        }}
      >
        {title}
        <Button
          onClick={onClose}
          sx={{ textTransform: "none", flexShrink: 0 }}
          data-testid="insights-view-all-close"
        >
          Close
        </Button>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, ...contentSx }}>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export default InsightsViewAllDialog;
