import { useCallback, useEffect, useMemo, useState } from "react";
import { Routes, Route, useNavigate, useLocation, useSearchParams } from "react-router-dom";
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
import ArticleOutlinedIcon from "@mui/icons-material/ArticleOutlined";

import AuthorSearch from "./components/authors/AuthorSearch";
import SelectedAuthorsList from "./components/authors/SelectedAuthorsList";
import AuthorAnalysisPage from "./components/authors/AuthorAnalysisPage";
import AuthorInsightsPage from "./features/authorAnalysis/AuthorInsightsPage";
import GrantPublicationsPage from "./components/grants/GrantPublicationsPage";
import { toAnalysisAuthorPayload } from "./api/analysisApi";
import { ENTITY_TYPES } from "./api/searchApi";
import {
  buildSearchHomePath,
  clearSelectionsForEntity,
  ENTITY_QUERY_PARAM,
  getActiveSearchMenuEntity,
  isSearchHomePath,
  parseEntityParam,
} from "./navigation/searchNavigation";

const drawerWidth = 270;

function AuthorSearchHome({
  drawerOpen,
  setDrawerOpen,
  entityType,
  onEntityTypeChange,
  selectedAuthors,
  setSelectedAuthors,
  selectedWorks,
  setSelectedWorks,
  selectedGrants,
}) {
  const navigate = useNavigate();

  const activeSelectedItems = useMemo(() => {
    if (
      entityType === ENTITY_TYPES.WORKS ||
      entityType === ENTITY_TYPES.GRANTS
    ) {
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

    const appendUnique = (current) => {
      if (current.some((entry) => entry.result_id === item.result_id)) {
        return current;
      }
      return [...current, item];
    };

    if (
      item.result_type === "work" ||
      entityType === ENTITY_TYPES.WORKS ||
      entityType === ENTITY_TYPES.GRANTS
    ) {
      setSelectedWorks(appendUnique);
      return;
    }
    setSelectedAuthors(appendUnique);
  };

  const handleItemRemoved = (resultId) => {
    if (
      entityType === ENTITY_TYPES.WORKS ||
      entityType === ENTITY_TYPES.GRANTS
    ) {
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
    if (
      entityType === ENTITY_TYPES.WORKS ||
      entityType === ENTITY_TYPES.GRANTS
    ) {
      setSelectedWorks([]);
      return;
    }
    setSelectedAuthors([]);
  };

  const handleAnalyze = () => {
    if (entityType !== ENTITY_TYPES.AUTHORS) {
      console.log("Analyze selection:", {
        entityType,
        selectedAuthors,
        selectedWorks,
        selectedGrants,
      });
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
          zIndex: 1,
        }}
      >
        <Typography
          variant="h3"
          component="h1"
          fontWeight={600}
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
        />
      </Box>

      <Box
        sx={{
          position: { xs: "static", md: "absolute" },
          top: { md: "calc(44% + 135px)" },
          left: { md: "50%" },
          transform: { md: "translateX(-50%)" },
          width: "100%",
          maxWidth: 760,
          minHeight: 320,
          px: 3,
          mx: { xs: "auto", md: 0 },
          pb: { xs: 4, md: 0 },
          zIndex: 1,
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

function App() {
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
  const [selectedGrants] = useState([]);

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

  useEffect(() => {
    if (!isSearchHomePath(location.pathname)) {
      return;
    }
    const parsed = parseEntityParam(searchParams.get(ENTITY_QUERY_PARAM));
    setEntityType((current) => {
      if (current === parsed) {
        return current;
      }
      clearSelectionsForEntity(parsed, selectionSetters);
      return parsed;
    });
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
          >
            <ListItemIcon>
              <PersonSearchRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Authors" />
          </ListItemButton>

          <ListItemButton
            selected={activeMenuEntity === ENTITY_TYPES.GRANTS}
            onClick={() => navigateToSearchEntity(ENTITY_TYPES.GRANTS)}
          >
            <ListItemIcon>
              <PaidRoundedIcon />
            </ListItemIcon>
            <ListItemText primary="Grants" />
          </ListItemButton>

          <ListItemButton
            selected={activeMenuEntity === ENTITY_TYPES.WORKS}
            onClick={() => navigateToSearchEntity(ENTITY_TYPES.WORKS)}
          >
            <ListItemIcon>
              <ArticleOutlinedIcon />
            </ListItemIcon>
            <ListItemText primary="Works / Publications" />
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
          minHeight: "100vh",
          transition: (theme) =>
            theme.transitions.create("margin", {
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
                selectedGrants={selectedGrants}
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
                selectedGrants={selectedGrants}
              />
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

export default App;
