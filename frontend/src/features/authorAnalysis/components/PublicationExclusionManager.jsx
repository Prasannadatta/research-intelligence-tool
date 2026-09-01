import { useState } from "react";
import {
  Box,
  Button,
  Chip,
  Collapse,
  Divider,
  Paper,
  Typography,
  useTheme,
} from "@mui/material";
import { getAnalysisPalette } from "../../../theme/analysisPalette";

function PublicationExclusionManager({
  excludedWorkIds,
  excludedWorksById = {},
  onRestore,
  onRestoreAll,
  compact = false,
}) {
  const theme = useTheme();
  const accents = getAnalysisPalette(theme);
  const [open, setOpen] = useState(false);
  const ids = Array.isArray(excludedWorkIds) ? excludedWorkIds : [...excludedWorkIds];
  const count = ids.length;

  if (count === 0) {
    return null;
  }

  return (
    <Paper
      elevation={0}
      data-testid="publication-exclusion-manager"
      sx={{
        p: compact ? 1.25 : 1.5,
        border: "1px solid",
        borderColor: "divider",
        borderRadius: "12px",
        mb: compact ? 1.5 : 2,
      }}
    >
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, flexWrap: "wrap" }}>
        <Chip
          size="small"
          label={`Excluded from Insights: ${count}`}
          data-testid="excluded-count"
          sx={{
            bgcolor: accents.amberSoft,
            color: theme.palette.mode === "dark" ? accents.amber : "text.secondary",
            fontWeight: 600,
          }}
        />
        <Button size="small" onClick={() => setOpen((value) => !value)} sx={{ textTransform: "none" }}>
          {open ? "Hide" : "Review"}
        </Button>
        <Button size="small" onClick={onRestoreAll} sx={{ textTransform: "none" }}>
          Restore all
        </Button>
      </Box>
      <Collapse in={open}>
        <Divider sx={{ my: 1 }} />
        <Box sx={{ display: "grid", gap: 0.75 }}>
          {ids.map((id) => {
            const work = excludedWorksById[id] || {};
            const title = work.title || id;
            const year = work.publication_year || work.year || null;
            return (
              <Box
                key={id}
                data-testid={`excluded-work-${id}`}
                sx={{
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "space-between",
                  gap: 1,
                }}
              >
                <Typography variant="body2" sx={{ minWidth: 0, wordBreak: "break-word" }}>
                  {title}
                  {year ? (
                    <Typography component="span" variant="caption" color="text.secondary">
                      {" "}
                      ({year})
                    </Typography>
                  ) : null}
                </Typography>
                <Button size="small" onClick={() => onRestore?.(id)} sx={{ textTransform: "none" }}>
                  Restore
                </Button>
              </Box>
            );
          })}
        </Box>
      </Collapse>
    </Paper>
  );
}

export default PublicationExclusionManager;
