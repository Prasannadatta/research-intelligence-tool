import { Box, Checkbox, FormControlLabel, Typography } from "@mui/material";

function AuthorIncludedSelector({
  authors = [],
  activeAuthorIds,
  onToggleAuthor,
  getDisabled,
  title = "Authors included",
  "data-testid": dataTestId,
  sx,
}) {
  return (
    <Box sx={{ mb: 1.5, ...sx }} data-testid={dataTestId}>
      <Typography
        variant="body2"
        color="text.secondary"
        sx={{ mb: 0.75, fontWeight: 600 }}
      >
        {title}
      </Typography>
      <Box
        sx={{
          display: "flex",
          flexWrap: "wrap",
          gap: { xs: 0.5, sm: 1 },
          alignItems: "center",
        }}
      >
        {authors.map((author) => {
          const authorId = author.canonical_author_id;
          const checked = activeAuthorIds.has(authorId);
          const disabled = getDisabled?.(authorId, checked) || false;
          return (
            <FormControlLabel
              key={authorId}
              control={
                <Checkbox
                  size="small"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => onToggleAuthor?.(authorId)}
                  slotProps={{
                    input: { "aria-label": author.display_name },
                  }}
                  sx={{ py: 0.25 }}
                />
              }
              label={
                <Typography variant="body2" sx={{ lineHeight: 1.4, fontWeight: 400 }}>
                  {author.display_name}
                </Typography>
              }
              sx={{
                m: 0,
                mr: 1,
                "& .MuiFormControlLabel-label": {
                  color: checked ? "text.primary" : "text.secondary",
                },
              }}
            />
          );
        })}
      </Box>
    </Box>
  );
}

export default AuthorIncludedSelector;
