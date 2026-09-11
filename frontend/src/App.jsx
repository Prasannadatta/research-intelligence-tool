import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Routes,
  Route,
  useNavigate,
  useLocation,
  useSearchParams,
} from "react-router-dom";
import {
  Box,
  Drawer,
  IconButton,
  List,
  ListItemButton,
  ListItemIcon,
  ListItemText,
  Tooltip,
  Typography,
} from "@mui/material";
import { useColorScheme } from "@mui/material/styles";

import MenuRoundedIcon from "@mui/icons-material/MenuRounded";
import MenuOpenRoundedIcon from "@mui/icons-material/MenuOpenRounded";
import LightModeRoundedIcon from "@mui/icons-material/LightModeRounded";
import DarkModeRoundedIcon from "@mui/icons-material/DarkModeRounded";
import PersonSearchRoundedIcon from "@mui/icons-material/PersonSearchRounded";
import PaidRoundedIcon from "@mui/icons-material/PaidRounded";
import BookmarkBorderRoundedIcon from "@mui/icons-material/BookmarkBorderRounded";
import SyncRoundedIcon from "@mui/icons-material/SyncRounded";


import AuthorSearch from "./components/authors/AuthorSearch";
import SelectedAuthorsList from "./components/authors/SelectedAuthorsList";
import AuthorAnalysisPage from "./components/authors/AuthorAnalysisPage";
import AuthorDetailsPage from "./components/authors/AuthorDetailsPage";
import AuthorInsightsPage from "./features/authorAnalysis/AuthorInsightsPage";
import SavedSearchesPage from "./features/savedSearches/SavedSearchesPage";
import DataUpdaterPage from "./features/dataUpdater/DataUpdaterPage";
import GrantPublicationsPage from "./components/grants/GrantPublicationsPage";
import { toAnalysisAuthorPayload } from "./api/analysisApi";
import { ENTITY_TYPES } from "./api/searchApi";
import { resolveAuthorSelection } from "./api/authorResolveApi";
import {
  buildSearchHomePath,
  clearSelectionsForEntity,
  ENTITY_QUERY_PARAM,
  getActiveSearchMenuEntity,
  isSearchHomePath,
  parseEntityParam,
} from "./navigation/searchNavigation";
import { getAnalysisPalette } from "./theme/analysisPalette";
import {
  analysisPagePaddingLeftVar,
  closedDrawerContentInset,
} from "./layout/pageLayout";

const drawerWidth = 270;
const navItemSx = (theme) => {
  const accents = getAnalysisPalette(theme);
  return {
    "&.Mui-selected": {
      bgcolor: accents.navySoft,
      color: accents.navy,
      "& .MuiListItemIcon-root": {
        color: accents.navy,
      },
      "& .MuiListItemText-primary": {
        fontWeight: 600,
      },
    },
    "&.Mui-selected:hover": {
      bgcolor: accents.navySoft,
    },
  };
};

function AuthorSearchHome({
  drawerOpen,
  setDrawerOpen,
  entityType,
  onEntityTypeChange,
  selectedAuthors,
  setSelectedAuthors,
  selectedWorks,
  setSelectedWorks,
}) {
  const navigate = useNavigate();

  const activeSelectedItems = useMemo(() => {
    if (entityType === ENTITY_TYPES.GRANTS) {
      return selectedWorks;
    }
    return selectedAuthors;
  }, [entityType, selectedAuthors, selectedWorks]);

  const activeSelectedIds = useMemo(
    () => activeSelectedItems.map((item) => item.result_id).filter(Boolean),
    [activeSelectedItems],
  );

  const handleResultSelected = (item) => {
    if (!item?.result_id) {
      return;
    }

    const appendUnique = (current, nextItem) => {
      const nextId = nextItem?.result_id;
      if (!nextId) {
        return current;
      }
      if (current.some((entry) => entry.result_id === nextId || entry.id === nextId)) {
        return current;
      }
      // Drop a prior unresolved row for the same provider identity if present.
      const providerKey =
        nextItem?.openalex_id ||
        nextItem?.orcid ||
        nextItem?.source_records?.[0]?.provider_author_id;
      const filtered = providerKey
        ? current.filter((entry) => {
            const entryKey =
              entry?.openalex_id ||
              entry?.orcid ||
              entry?.source_records?.[0]?.provider_author_id;
            return entryKey !== providerKey;
          })
        : current;
      return [...filtered, nextItem];
    };

    if (item.result_type === "work" || entityType === ENTITY_TYPES.GRANTS) {
      setSelectedWorks((current) => appendUnique(current, item));
      return;
    }

    // Resolve identity on selection (not during typeahead).
    void (async () => {
      let resolved = item;
      try {
        resolved = await resolveAuthorSelection(item);
      } catch {
        resolved = item;
      }
      setSelectedAuthors((current) => appendUnique(current, resolved));
    })();
  };

  const handleItemRemoved = (resultId) => {
    if (entityType === ENTITY_TYPES.GRANTS) {
      setSelectedWorks((current) =>
        current.filter((item) => item.result_id !== resultId),
      );
      return;
    }
    setSelectedAuthors((current) =>
      current.filter((item) => item.result_id !== resultId),
    );
  };

  const handleClearAll = () => {
    if (entityType === ENTITY_TYPES.GRANTS) {
      setSelectedWorks([]);
      return;
    }
    setSelectedAuthors([]);
  };

  const handleAnalyze = () => {
    if (entityType !== ENTITY_TYPES.AUTHORS) {
      return;
    }

    const authors = selectedAuthors
      .map((item) => toAnalysisAuthorPayload(item))
      .filter(Boolean);

    if (authors.length === 0) {
      return;
    }

    navigate("/analyze/authors", {
      state: { authors },
    });
  };

  return (
    <Box
      sx={{
        position: "relative",
        minHeight: "100vh",
        width: "100%",
        overflow: { xs: "auto", md: "hidden" },
      }}
    >
      {!drawerOpen && (
        <Tooltip title="Open sidebar">
          <IconButton
            onClick={() => setDrawerOpen(true)}
            sx={{
              position: "absolute",
              top: 18,
              left: 18,
              zIndex: 10,
            }}
          >
            <MenuRoundedIcon />
          </IconButton>
        </Tooltip>
      )}

      <Box
        id="stable-search-section"
        sx={{
          position: { xs: "static", md: "absolute" },
          top: { md: "44%" },
          left: { md: "50%" },
          transform: { md: "translate(-50%, -50%)" },
          width: "100%",
          maxWidth: 760,
          px: 3,
          pt: { xs: 10, md: 0 },
          mx: { xs: "auto", md: 0 },
          textAlign: "center",
          // Keep search + filters above the selected-authors slot so chips stay clickable.
          zIndex: 2,
        }}
      >
        <Typography
          variant="h3"
          component="h1"
          fontWeight={700}
          sx={{
            mb: 1.5,
            fontSize: {
              xs: "2rem",
              sm: "2.6rem",
            },
          }}
        >
          What would you like to explore?
        </Typography>

        <Typography
          color="text.secondary"
          sx={{
            mb: 4,
            maxWidth: 600,
            mx: "auto",
            lineHeight: 1.7,
          }}
        >
          Search for a researcher, compare multiple authors, or monitor
          scientific publications connected to a grant.
        </Typography>

        <AuthorSearch
          key={entityType}
          entityType={entityType}
          onEntityTypeChange={onEntityTypeChange}
          onResultSelected={handleResultSelected}
          selectedResultIds={activeSelectedIds}
          selectedAuthors={
            entityType === ENTITY_TYPES.AUTHORS ? selectedAuthors : []
          }
        />
      </Box>

      <Box
        sx={{
          position: { xs: "static", md: "absolute" },
          // Leave room for always-visible Institution / Research area filters.
          top: { md: "calc(44% + 230px)" },
          left: { md: "50%" },
          transform: { md: "translateX(-50%)" },
          width: "100%",
          maxWidth: 760,
          minHeight: 320,
          px: 3,
          mx: { xs: "auto", md: 0 },
          pb: { xs: 4, md: 0 },
          zIndex: 1,
          // Empty slot must not intercept clicks on filter chips above it.
          pointerEvents: activeSelectedItems.length > 0 ? "auto" : "none",
        }}
      >
        <SelectedAuthorsList
          entityType={entityType}
          items={activeSelectedItems}
          onRemove={handleItemRemoved}
          onClearAll={handleClearAll}
          onAnalyze={handleAnalyze}
        />
      </Box>
    </Box>
  );
}

function AppShell() {
  const [drawerOpen, setDrawerOpen] = useState(true);
  const [entityType, setEntityType] = useState(() => {
    if (typeof window === "undefined") {
      return ENTITY_TYPES.AUTHORS;
    }
    if (!isSearchHomePath(window.location.pathname)) {
      return ENTITY_TYPES.AUTHORS;
    }
    const params = new URLSearchParams(window.location.search);
    return parseEntityParam(params.get(ENTITY_QUERY_PARAM));
  });
  const [selectedAuthors, setSelectedAuthors] = useState([]);
  const [selectedWorks, setSelectedWorks] = useState([]);

  const { mode, setMode } = useColorScheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [searchParams, setSearchParams] = useSearchParams();

  const selectionSetters = useMemo(
    () => ({
      setSelectedAuthors,
      setSelectedWorks,
    }),
    [],
  );

  const activeMenuEntity = getActiveSearchMenuEntity(location.pathname, searchParams);
  const savedSearchesSelected = location.pathname.startsWith("/saved-searches");
  const dataUpdaterSelected = location.pathname.startsWith("/data-updater");
  useEffect(() => {
    if (!isSearchHomePath(location.pathname)) {
      return;
    }
    const parsed = parseEntityParam(searchParams.get(ENTITY_QUERY_PARAM));
    /* eslint-disable react-hooks/set-state-in-effect -- URL query params are the source of truth for the search home selector. */
    setEntityType((current) => {
      if (current === parsed) {
        return current;
      }
      clearSelectionsForEntity(parsed, selectionSetters);
      return parsed;
    });
    /* eslint-enable react-hooks/set-state-in-effect */
  }, [location.pathname, searchParams, selectionSetters]);

  const handleEntityTypeChange = useCallback(
    (nextType) => {
      const parsed = parseEntityParam(nextType);
      if (
        parsed === entityType &&
        isSearchHomePath(location.pathname) &&
        parseEntityParam(searchParams.get(ENTITY_QUERY_PARAM)) === parsed
      ) {
        return;
      }
      clearSelectionsForEntity(parsed, selectionSetters);
      setEntityType(parsed);
      if (isSearchHomePath(location.pathname)) {
        setSearchParams({ [ENTITY_QUERY_PARAM]: parsed });
      }
    },
    [entityType, location.pathname, searchParams, selectionSetters, setSearchParams],
  );

  const navigateToSearchEntity = useCallback(
    (entity) => {
      const parsed = parseEntityParam(entity);
      clearSelectionsForEntity(parsed, selectionSetters);
      setEntityType(parsed);
      navigate(buildSearchHomePath(parsed));
    },
    [navigate, selectionSetters],
  );

  const toggleTheme = () => {
    setMode(mode === "dark" ? "light" : "dark");
  };

  return (
    <Box
      sx={{
        display: "flex",
        minHeight: "100vh",
        bgcolor: "background.default",
      }}
    >
      <Drawer
        variant="persistent"
        anchor="left"
        open={drawerOpen}
        sx={{
          width: drawerOpen ? drawerWidth : 0,
          flexShrink: 0,
          "& .MuiDrawer-paper": {
            width: drawerWidth,
            boxSizing: "border-box",
            borderRight: "1px solid",
            borderColor: "divider",
            bgcolor: "background.paper",
            p: 1.5,
          },
        }}
      >
        <Box
          sx={{
            display: "flex",
            alignItems: "center",
            justifyContent: "space-between",
            px: 1,
            py: 1,
          }}
        >
          <Typography
            component="button"
            type="button"
            variant="subtitle1"
            onClick={() => navigateToSearchEntity(ENTITY_TYPES.AUTHORS)}
            sx={{
              fontWeight: 800,
              border: 0,
              bgcolor: "transparent",
              cursor: "pointer",
              p: 0,
              m: 0,
              textAlign: "left",
              color: "text.primary",
              "&:hover": { color: "text.primary", opacity: 0.85 },
            }}
          >
            Research AI
          </Typography>

          <Tooltip title="Close sidebar">
            <IconButton onClick={() => setDrawerOpen(false)}>
              <MenuOpenRoundedIcon />
            </IconButton>
          </Tooltip>
        </Box>

        <List sx={{ mt: 2 }}>
          <ListItemButton
            selected={activeMenuEntity === ENTITY_TYPES.AUTHORS}
            onClick={() => navigateToSearchEntity(ENTITY_TYPES.AUTHORS)}
            sx={navItemSx}
          >
            <ListItemIcon>
              <PersonSearchRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Authors" />
          </ListItemButton>

          <ListItemButton
            selected={activeMenuEntity === ENTITY_TYPES.GRANTS}
            onClick={() => navigateToSearchEntity(ENTITY_TYPES.GRANTS)}
            sx={navItemSx}
          >
            <ListItemIcon>
              <PaidRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Grants" />
          </ListItemButton>

          <ListItemButton
            selected={savedSearchesSelected}
            onClick={() => navigate("/saved-searches")}
            sx={navItemSx}
          >
            <ListItemIcon>
              <BookmarkBorderRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Saved Searches" />
          </ListItemButton>

          <ListItemButton
            selected={dataUpdaterSelected}
            onClick={() => navigate("/data-updater")}
            sx={navItemSx}
          >
            <ListItemIcon>
              <SyncRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Data Updater" />
          </ListItemButton>

        </List>

        <Box sx={{ flexGrow: 1 }} />

        <List>
          <ListItemButton onClick={toggleTheme}>
            <ListItemIcon>
              {mode === "dark" ? (
                <LightModeRoundedIcon />
              ) : (
                <DarkModeRoundedIcon />
              )}
            </ListItemIcon>

            <ListItemText
              primary={mode === "dark" ? "Light mode" : "Dark mode"}
            />
          </ListItemButton>
        </List>
      </Drawer>

      <Box
        component="main"
        sx={{
          position: "relative",
          flexGrow: 1,
          minWidth: 0,
          boxSizing: "border-box",
          [analysisPagePaddingLeftVar]: {
            xs: "16px",
            sm: "24px",
            md: drawerOpen ? "32px" : `${closedDrawerContentInset}px`,
          },
          width: {
            xs: "100%",
            md: drawerOpen ? `calc(100% - ${drawerWidth}px)` : "100%",
          },
          minHeight: "100vh",
          transition: (theme) =>
            theme.transitions.create("width", {
              easing: theme.transitions.easing.sharp,
              duration: theme.transitions.duration.leavingScreen,
            }),
        }}
      >
        <Routes>
          <Route
            path="/"
            element={
              <AuthorSearchHome
                drawerOpen={drawerOpen}
                setDrawerOpen={setDrawerOpen}
                entityType={entityType}
                onEntityTypeChange={handleEntityTypeChange}
                selectedAuthors={selectedAuthors}
                setSelectedAuthors={setSelectedAuthors}
                selectedWorks={selectedWorks}
                setSelectedWorks={setSelectedWorks}
              />
            }
          />
          <Route
            path="/search"
            element={
              <AuthorSearchHome
                drawerOpen={drawerOpen}
                setDrawerOpen={setDrawerOpen}
                entityType={entityType}
                onEntityTypeChange={handleEntityTypeChange}
                selectedAuthors={selectedAuthors}
                setSelectedAuthors={setSelectedAuthors}
                selectedWorks={selectedWorks}
                setSelectedWorks={setSelectedWorks}
              />
            }
          />
          <Route
            path="/authors/:id"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <AuthorDetailsPage />
              </Box>
            }
          />
          <Route
            path="/analyze/authors/insights"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <AuthorInsightsPage />
              </Box>
            }
          />
          <Route
            path="/analyze/authors"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <AuthorAnalysisPage />
              </Box>
            }
          />
          <Route
            path="/saved-searches"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <SavedSearchesPage />
              </Box>
            }
          />
          <Route
            path="/data-updater"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <DataUpdaterPage />
              </Box>
            }
          />
          <Route
            path="/grants/:grantNumber"
            element={
              <Box sx={{ position: "relative", minHeight: "100vh" }}>
                {!drawerOpen && (
                  <Tooltip title="Open sidebar">
                    <IconButton
                      onClick={() => setDrawerOpen(true)}
                      sx={{
                        position: "absolute",
                        top: 18,
                        left: 18,
                        zIndex: 10,
                      }}
                    >
                      <MenuRoundedIcon />
                    </IconButton>
                  </Tooltip>
                )}
                <GrantPublicationsPage />
              </Box>
            }
          />
        </Routes>
      </Box>
    </Box>
  );
}

function App() {
  return <AppShell />;
}

export default App;
