"""BoulderRunner — orchestrator for the YAML → network → result pipeline.

Provides a single class that subclasses can override to inject custom
converters (e.g. ``BlocRunner`` with ``BlocConverter``).  The Boulder CLI
uses the base class; Bloc CLI passes ``runner_class=BlocRunner``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Optional, Type

if TYPE_CHECKING:
    import cantera as ct
    from boulder.cantera_converter import BoulderPlugins, DualCanteraConverter
    from boulder.simulation_result import SimulationResult


class BoulderRunner:
    """Orchestrates the full YAML-to-SimulationResult pipeline.

    Subclass and set ``converter_class`` to swap the converter without
    touching any other code.  All public attributes are documented; no private
    underscore fields are accessed by callers.

    Parameters
    ----------
    config :
        Normalised (and validated) config dict.
    plugins :
        Optional pre-built plugin container.  When ``None`` the converter
        will discover plugins via entry-points.
    config_path :
        Original path of the YAML file; propagated to the converter so the
        downloadable script references the correct file.
    """

    converter_class: Type["DualCanteraConverter"] = None  # type: ignore[assignment]

    def __init__(
        self,
        config: Dict[str, Any],
        *,
        plugins: Optional["BoulderPlugins"] = None,
        config_path: Optional[str] = None,
    ) -> None:
        self.config = config
        self.config_path = config_path
        self.plugins = plugins
        self.converter: Optional["DualCanteraConverter"] = None
        self.network: Optional["ct.ReactorNet"] = None
        self.results: Optional[Dict[str, Any]] = None
        self.code: Optional[str] = None
        self.result: Optional["SimulationResult"] = None

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if "converter_class" not in cls.__dict__:
            # Inherit from parent; no default assignment needed.
            pass

    @classmethod
    def from_yaml(cls, path: str) -> "BoulderRunner":
        """Load, normalise, and validate a YAML file, returning a runner instance."""
        cfg = cls.validate(cls.normalize(cls.load(path)))
        return cls(config=cfg, config_path=path)

    @staticmethod
    def load(path: str) -> Dict[str, Any]:
        """Load raw config dict from a YAML file."""
        from .config import load_config_file
        return load_config_file(path)

    @classmethod
    def normalize(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Apply Boulder's structural normalisation to a raw config."""
        from .config import normalize_config
        return normalize_config(cfg)

    @classmethod
    def validate(cls, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Validate a normalised config, raising on schema errors."""
        from .config import validate_config
        return validate_config(cfg)

    def _default_mechanism_name(self) -> str:
        """Return the raw top-level mechanism string (not path-resolved).

        Path resolution happens inside ``DualCanteraConverter.resolve_mechanism``,
        which is called during construction.
        """
        phases = self.config.get("phases") or {}
        gas = phases.get("gas") if isinstance(phases, dict) else {}
        return (gas or {}).get("mechanism") or "gri30.yaml"

    def build(self) -> "BoulderRunner":
        """Instantiate the converter, build and solve the staged network.

        Returns ``self`` for chaining.  After this call:
        - ``self.converter`` is the :class:`~boulder.cantera_converter.DualCanteraConverter`.
        - ``self.network`` is the visualisation :class:`~cantera.ReactorNet`.
        - ``self.results`` is the raw results dict from the converter.
        - ``self.code`` is the generated standalone Python script string.
        """
        from .cantera_converter import DualCanteraConverter

        converter_cls = self.__class__.converter_class or DualCanteraConverter
        self.converter = converter_cls(
            mechanism=self._default_mechanism_name(),
            plugins=self.plugins,
        )
        if self.config_path is not None:
            self.converter._download_config_path = self.config_path
        self.network, self.results, self.code = (
            self.converter.build_network_and_code(self.config)
        )
        return self

    def solve(self) -> "BoulderRunner":
        """Build (if not done) and produce a typed :class:`~boulder.SimulationResult`.

        Returns ``self`` for chaining.
        """
        if self.network is None:
            self.build()
        from .simulation_result import make_simulation_result
        self.result = make_simulation_result(self.converter, self.config)
        return self

    def run_headless(
        self,
        *,
        download_path: Optional[str] = None,
        simulate: bool = True,
        end_time: Optional[float] = None,
        dt: Optional[float] = None,
    ) -> "BoulderRunner":
        """Solve the network and optionally write a downloadable Python script.

        This is the single source of truth for the ``--headless --download``
        CLI flow.  Both ``boulder`` and ``bloc`` CLIs call this method so the
        generated scripts are always identical (same code path, same converter).

        Parameters
        ----------
        download_path :
            Path to write the standalone Python script.  Skipped when ``None``.
        simulate :
            When ``True`` and ``end_time`` is set, run ``run_streaming_simulation``
            to append the time-advance section to the generated code.
        end_time :
            Simulation end time in seconds (from ``settings.end_time`` in the YAML).
        dt :
            Simulation time step in seconds (from ``settings.dt`` in the YAML).
        """
        self.solve()
        if simulate:
            # Always call run_streaming_simulation so the downloadable script
            # contains the full reactor-state reporting section.  When the YAML
            # has no end_time we use a dummy 0.0 so only the steady-state report
            # is emitted (no time-stepping), which mirrors the old headless path.
            self.converter.run_streaming_simulation(
                simulation_time=float(end_time) if end_time is not None else 0.0,
                time_step=(dt or 1.0),
                config=self.config,
            )
            self.code = "\n".join(self.converter.code_lines)
        if download_path is not None:
            with open(download_path, "w", encoding="utf-8") as fh:
                fh.write(self.code or "")
        return self
