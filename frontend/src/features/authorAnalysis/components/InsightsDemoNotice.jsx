import { Alert } from "@mui/material";

import { DEMO_NOTICE } from "../mockAuthorInsightsData";

function InsightsDemoNotice({ message = DEMO_NOTICE }) {
  return (
    <Alert
      severity="info"
      variant="outlined"
      data-testid="insights-demo-notice"
      sx={{
        mb: 2.5,
        borderRadius: "14px",
        "& .MuiAlert-message": { width: "100%" },
      }}
    >
      {message}
    </Alert>
  );
}

export default InsightsDemoNotice;
