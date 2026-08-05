import { useMemo, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { Box, Typography } from "@mui/material";

import {
  getMockAuthorInsightsData,
  getPublicationsForCombination,
  resolveSelectedAuthorNames,
} from "./mockAuthorInsightsData";
import AuthorInsightsHeader from "./components/AuthorInsightsHeader";
import InsightsDemoNotice from "./components/InsightsDemoNotice";
import InsightsMetricCards from "./components/InsightsMetricCards";
import AuthorCombinationChart from "./components/AuthorCombinationChart";
import AuthorCombinationTable from "./components/AuthorCombinationTable";
import CollaborationYearChart from "./components/CollaborationYearChart";
import ParticipationDonuts from "./components/ParticipationDonuts";
import InstitutionNetworkPreview from "./components/InstitutionNetworkPreview";
import InstitutionPartnershipTable from "./components/InstitutionPartnershipTable";
import CitationActivityChart from "./components/CitationActivityChart";
import TopJournalsTable from "./components/TopJournalsTable";
import InsightsPublicationPreview from "./components/InsightsPublicationPreview";

const pageLayoutSx = {
  width: "100%",
  maxWidth: "none",
  px: { xs: 2, sm: 3, md: 6 },
  py: 3,
  boxSizing: "border-box",
  textAlign: "left",
};

function AuthorInsightsPage() {
  const navigate = useNavigate();
  const location = useLocation();

  const authorNames = useMemo(
    () => resolveSelectedAuthorNames(location.state),
    [location.state],
  );

  const data = useMemo(
    () => getMockAuthorInsightsData({ authorNames }),
    [authorNames],
  );

  const [selectedCombinationId, setSelectedCombinationId] = useState(
    data.defaultCombinationId,
  );

  const selectedCombination = useMemo(
    () =>
      data.combinations.find((row) => row.id === selectedCombinationId) ||
      data.combinations[0],
    [data.combinations, selectedCombinationId],
  );

  const previewPublications = useMemo(
    () => getPublicationsForCombination(data, selectedCombination?.id),
    [data, selectedCombination],
  );

  const handleBack = () => {
    navigate("/analyze/authors", {
      state: location.state?.authors ? { authors: location.state.authors } : undefined,
    });
  };

  return (
    <Box sx={pageLayoutSx} data-testid="author-insights-page">
      <InsightsDemoNotice />

      <AuthorInsightsHeader authorNames={data.authorNames} onBack={handleBack} />

      <InsightsMetricCards metrics={data.metrics} />

      <AuthorCombinationChart
        combinations={data.combinations}
        selectedId={selectedCombination?.id}
        onSelect={setSelectedCombinationId}
      />
      <AuthorCombinationTable
        combinations={data.combinations}
        selectedId={selectedCombination?.id}
        onSelect={setSelectedCombinationId}
      />

      <CollaborationYearChart collaborationByYear={data.collaborationByYear} />

      <Typography variant="h6" fontWeight={600} sx={{ mb: 0.5 }}>
        Multi-author and multi-institution publication breakdown
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        How often selected authors and institutions co-appear in the demo set.
      </Typography>
      <ParticipationDonuts participation={data.participation} />

      <Typography variant="h6" fontWeight={600} sx={{ mb: 0.5 }}>
        Institution partnerships
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        A simple preview of co-publishing institutions.
      </Typography>
      <Box
        data-testid="institution-partnerships-section"
        sx={{
          display: "grid",
          gridTemplateColumns: { xs: "1fr", md: "1fr 1fr" },
          gap: 2,
          mb: 2.5,
          alignItems: "stretch",
        }}
      >
        <InstitutionNetworkPreview network={data.institutionNetwork} />
        <InstitutionPartnershipTable partnerships={data.institutionPartnerships} />
      </Box>

      <CitationActivityChart citationActivity={data.citationActivity} />

      <TopJournalsTable journals={data.topJournals} />

      <InsightsPublicationPreview
        publications={previewPublications}
        combinationLabel={selectedCombination?.label}
        onBack={handleBack}
      />
    </Box>
  );
}

export default AuthorInsightsPage;
