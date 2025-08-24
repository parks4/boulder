"""Sankey diagrams tools for Bloc."""

from .ctutils import collect_all_reactors_and_reservoirs


def plot_sankey_diagram(sim, mechanism="gri30.yaml"):
    """Plot Sankey Diagram for a simulation.

    Show the figure by default. If you want the figure without showing it, use
    :py:func:`~boulder.sankey.plot_sankey_diagram_from_links_and_nodes`.

    Parameters
    ----------
    sim : Cantera ReactorNet object
        A ReactorNet instance containing a list of reactors; already resolved.
    mechanism : str
        Cantera mechanism file to use for heating value calculations. Default is "gri30.yaml".

    Example
    -------
    ::

        sim.advance_to_steady_state()
        plot_sankey_diagram(sim)

    See Also
    --------
    :py:func:`~boulder.sankey.generate_sankey_input_from_sim`,
    :py:func:`~boulder.sankey.plot_sankey_diagram_from_links_and_nodes`
    """
    # Ref:  https://python-graph-gallery.com/sankey-diagram-with-python-and-plotly/

    # Generate Sankey data:
    # ---------------------
    links, nodes = generate_sankey_input_from_sim(
        sim, show_species=["H2", "CH4"], mechanism=mechanism
    )

    # Plot Sankey Diagram:
    # --------------------
    plot_sankey_diagram_from_links_and_nodes(links, nodes, show=True)


def plot_sankey_diagram_from_links_and_nodes(links, nodes, show=False, theme="light"):
    """Plot Sankey Diagram from links and nodes.

    Parameters
    ----------
    links : dict
        Dictionary containing the links for the sankey diagram.
    nodes : list
        List of nodes for the sankey diagram.
    show : bool
        Whether to show the plot or not. Default is False.
    theme : str
        Theme to use for styling ("light" or "dark"). Default is "light".

    Returns
    -------
    plotly.graph_objects.Figure
        The Sankey diagram.
    """
    # Plot :
    # ------
    import plotly.graph_objects as go

    from .utils import get_sankey_theme_config

    sankey_theme = get_sankey_theme_config(theme)
    link_color_map = sankey_theme["link_colors"]

    # Create a copy to avoid modifying the original dict from dcc.Store
    links_with_colors = links.copy()
    links_with_colors["color"] = [link_color_map.get(c, "grey") for c in links["color"]]

    # Get theme-specific colors for nodes
    if theme == "dark":
        node_color = "#4A90E2"
        node_line_color = "#222222"
    else:
        node_color = "grey"
        node_line_color = "black"

    fig = go.Figure(
        data=go.Sankey(
            arrangement="snap",
            node={
                "label": nodes,
                "pad": 11,
                "line": dict(color=node_line_color, width=0.5),
                "thickness": 20,
                "color": node_color,
            },
            link=links_with_colors,
        )
    )
    if show:
        fig.show()
    return fig


def generate_sankey_input_from_sim(
    sim,
    node_order=[],
    flow_type="hhv",
    show_species=[],
    verbose=False,
    mechanism="gri30.yaml",
):
    """Generate input data for sankey plot from a Cantera Reactor Net simulation.

    Parameters
    ----------
    sim : Cantera ReactorNet object
        A ReactorNet instance containing a list of reactors.
    node_order : list of str
        Order for the nodes in the sankey diagram (optional).
        In case no order is passed, a generic order will be used.
    flow_type : str
        Type of flow to be considered in the sankey diagram. Default is "hhv".
        # TODO : implement other types of flow (e.g. "enthalpy", "exergy", etc.)
    show_species : list of str
        List of species to show in the sankey diagram.
        Set to [] not to show any species. Default is [].
    mechanism : str
        Cantera mechanism file to use for heating value calculations. Default is "gri30.yaml".

    Other Parameters
    ----------------
    verbose : bool
        if True, print details about Sankey network generation.

    Returns
    -------
    tuple
        Tuple containing the links and node_order for the plotly sankey
        diagram.

    Example
    -------
    ::

        links, nodes = generate_sankey_input_from_sim(sim)

        import plotly.graph_objects as go

        fig = go.Figure(go.Sankey(
            arrangement='snap',
            node={
                'label': nodes,
                'pad':11,
                'color': 'orange'
            },
            link=links
        ))
        fig.show()

    .. minigallery:: boulder.sankey.generate_sankey_input_from_sim

    See Also
    --------
    :py:func:`~boulder.sankey.plot_sankey_diagram`
    """
    all_reactors = list(collect_all_reactors_and_reservoirs(sim))
    if verbose:
        print("ALL REACTORS", [r.name for r in all_reactors])

    if node_order == []:
        node_order = [reactor.name for reactor in all_reactors]
    else:
        assert set(node_order) == set([reactor.name for reactor in all_reactors])

    links = {"source": [], "target": [], "value": [], "color": [], "label": []}

    # Create nodes for each reactor
    # ... sort all_reactors list using the reactor.name key, and the order defined in node_order
    nodes = sorted(all_reactors, key=lambda r: node_order.index(r.name))

    # Create links based on the flow rates between reactors
    for i, reactor in enumerate(nodes):
        if verbose:
            print(
                f"Parsing {reactor.name} : outlets = {[r.name for r in reactor.outlets]}"
            )
        # Parse Outlets = Mass flows out of the Reactor
        for outlet in reactor.outlets:
            target_reactor = outlet.downstream
            j = node_order.index(target_reactor.name)
            if target_reactor:
                flow_rate = outlet.mass_flow_rate  # kg/s0
                if flow_type == "enthalpy":
                    upstream_enthalpy = outlet.upstream.thermo.enthalpy_mass  # J/kg
                    energy_rate = flow_rate * upstream_enthalpy  # J/s = W
                    assert energy_rate > 0
                    links["source"] += [i]
                    links["target"] += [j]
                    links["value"] += [energy_rate]
                    links["color"] += ["enthalpy"]
                    links["label"] += ["Enthalpy (W)"]
                elif flow_type == "hhv":
                    # Add a first link with HHV
                    # -------------------------
                    from .ctutils import heating_values

                    lhv, hhv = heating_values(
                        outlet.upstream.thermo, mechanism=mechanism
                    )  # J/kg
                    # TODO define temperature reference when computing HHV
                    # (and make it consistent with the one used in sensible enthalpy)
                    energy_rate = flow_rate * hhv  # J/s = W

                    for s in show_species:
                        import cantera as ct

                        if s == "H2":
                            lhv_s, hhv_s = heating_values(
                                ct.Hydrogen(), mechanism=mechanism
                            )  # J/kg
                            links["color"] += ["H2"]
                        elif s == "CH4":
                            lhv_s, hhv_s = heating_values(
                                ct.Methane(), mechanism=mechanism
                            )  # J/kg
                            links["color"] += ["CH4"]
                        elif s == "C(s)":  # Carbon
                            raise NotImplementedError(f"{s} not implemented yet")
                            links["color"] += ["Cs"]
                        else:
                            raise NotImplementedError(f"{s} not implemented yet")

                        energy_rate_s = (
                            flow_rate * outlet.upstream.thermo[s].Y * hhv_s
                        )  # J/s = W
                        # remove energy rate of this species from the remaining energy rate:
                        energy_rate -= energy_rate_s
                        links["value"] += [energy_rate_s]
                        links["source"] += [i]
                        links["target"] += [j]
                        links["label"] += [f"HHV {s} (W)"]

                    links["source"] += [i]
                    links["target"] += [j]
                    links["value"] += [energy_rate]
                    links["color"] += ["enthalpy"]
                    links["label"] += ["HHV (W)"]

                    # Add a second link with sensible enthalpy
                    # ----------------------------------------
                    from .ctutils import get_STP_properties_IUPAC

                    _, enthalpy_STP = get_STP_properties_IUPAC(outlet.upstream.thermo)
                    sensible_enthalpy = (
                        outlet.upstream.thermo.enthalpy_mass - enthalpy_STP
                    )  # J/kg

                    sensible_energy_rate = flow_rate * sensible_enthalpy  # J/s = W
                    links["source"] += [i]
                    links["target"] += [j]
                    links["value"] += [sensible_energy_rate]
                    links["color"] += ["heat"]
                    links["label"] += ["Heat (W)"]

                else:
                    raise NotImplementedError(f"Unknown flow_type {flow_type}")

            else:
                if verbose:
                    print(f"no target found for {reactor.name}")
                pass
        # Parse Walls = energy flows (equivalent to "Bus" in Tespy)
        for wall in reactor.walls:
            if reactor == wall.left_reactor:
                target_reactor = wall.right_reactor
                j = node_order.index(target_reactor.name)
                heat_rate = wall.heat_rate  # W
                if flow_type not in ["hhv", "enthalpy"]:
                    raise NotImplementedError(
                        f"Unsupported heat rate when flow_rate is {flow_type}"
                    )
                if wall.heat_rate > 0:
                    links["source"] += [i]
                    links["target"] += [j]
                    links["value"] += [heat_rate]
                    links["color"] += ["heat"]
                    links["label"] += ["Power (W)"]
                elif wall.heat_rate < 0:
                    links["source"] += [j]
                    links["target"] += [i]
                    links["value"] += [-heat_rate]
                    links["color"] += ["heat"]
                    links["label"] += ["Power (W)"]
                else:
                    if verbose:
                        print(f"no heat rate found for {reactor.name}")
                    pass
            elif reactor == wall.right_reactor:
                pass  # do not count twice
            else:
                raise ValueError

    return links, node_order
    # output format is made similar to the one in Tespy
    # https://github.com/oemof/tespy/blob/dd0059c0d993c00d8d99fc87de1e4246ec6a684d/src/tespy/tools/analyses.py#L810


# Functions to edit Sankey diagrams ;
# for instance emulate recirculations


def get_outlet_value(links, nodes, node_name, filter_links="", get_color=False):
    """Get the sum of all outlet streams of a node.

    Also returns the color of the largest link.

    Parameters
    ----------
    links : dict
        Network links. Dictionary with keys {'source', 'target', 'value', 'color', 'label'}
    nodes : list
        Network list of names of nodes.
    node_name : str
        Name of the node.
    filter_links : str
        Expression to capture name of output streams to aggregate. Default is "",
        i.e. all output streams are aggregated. Example::

            filter_links = "H2|CH4"
    get_color: str
        If True, get color of the largest link. The default is False.
    """
    idx = nodes.index(node_name)
    # all links with source = idx
    all_links = [i for i, s in enumerate(links["source"]) if s == idx]
    # filter with regex filter_links:
    if filter_links:
        import re

        all_links = [i for i in all_links if re.match(filter_links, links["label"][i])]

    # sort by value
    all_links.sort(key=lambda i: links["value"][i], reverse=True)

    # sum values for all outlet streams:
    value = sum([links["value"][i] for i in all_links])

    if get_color:
        color = links["color"][all_links[0]]
        return value, color
    else:
        return value


def add_link(links, nodes, source_str, target_str, value, color=None, label=None):
    """Add a connection between Source and Target.

    Parameters
    ----------
    links : dict
        Dictionary of links, with keys {'source', 'target', 'value', 'color', 'label'}
    nodes : list
        list of names of nodes.
    source_str : str
        Name of the source node.
    target_str : str
        Name of the target node.
    value : float
        Value of the link.
    color : str, optional
        Color of the link. The default is None.
    label : str, optional
        Label of the link. The default is None.
    """
    # Add the link
    assert source_str in nodes, f"source_str not in nodes: {source_str}"
    assert target_str in nodes, f"target_str not in nodes: {target_str}"
    links["source"].append(nodes.index(source_str))
    links["target"].append(nodes.index(target_str))
    links["value"].append(value)
    if color is None:
        color = "grey"
    links["color"].append(color)
    if label is None:
        label = ""
    links["label"].append(label)


def substract_value(
    links, nodes, source_str, target_str, value, link_name=None, allow_negative=False
):
    """Substract a value from a link.

    Parameters
    ----------
    links : dict
        Dictionary of links, with keys {'source', 'target', 'value', 'color', 'label'}
    nodes : list
        list of names of nodes.
    source_str : str
        Name of the source node.
    target_str : str
        Name of the target node.
    value : float
        Value to substract from existing link.
    link_name : str, optional
        Name of the link. The default is None.
    allow_negative : bool, optional
        Allow negative values. The default is False. If True, the value being subtracted
        cannot be greater than the existing value.

    Returns
    -------
    None
        links and nodes are modified in place.
    """
    # Find the index of the link
    if link_name is None:
        idx = [
            i
            for i, (s, t) in enumerate(zip(links["source"], links["target"]))
            if s == nodes.index(source_str) and t == nodes.index(target_str)
        ]
        assert len(idx) == 1, (
            f"Found {len(idx)} links between {source_str} and {target_str}"
        )
        idx = idx[0]
    else:  # find link by "link_name"
        # assert link name exists
        assert link_name in links["label"], f"Link name not found: {link_name}"
        idx = [
            i
            for i, (s, t) in enumerate(zip(links["source"], links["target"]))
            if s == nodes.index(source_str) and t == nodes.index(target_str)
        ]
        # filter by link name
        idx = [i for i in idx if links["label"][i] == link_name]
        assert len(idx) == 1, (
            f"Found {len(idx)} links between {source_str} and {target_str} with label {link_name}"
        )
        idx = idx[0]

    # Substract the value
    if not allow_negative:
        assert links["value"][idx] >= value, (
            f"Value to substract is greater than existing value: {value} > {links['value'][idx]}"
        )
    links["value"][idx] -= value


if __name__ == "__main__":
    from bloc.test import default_simulation, defaults

    config = defaults()
    sim = default_simulation(**config)

    sim.advance_to_steady_state()

    links, nodes = generate_sankey_input_from_sim(sim, show_species=["H2", "CH4"])

    print("RESULT: ")
    print("Source:", links["source"])
    print("Target:", links["target"])
    print("Value :", links["value"])

    import plotly.graph_objects as go

    fig = go.Figure(
        data=go.Sankey(
            # arrangement='snap',
            node={
                "label": nodes,
                "pad": 11,
                #'line': dict(color = "black", width = 0.5),
                "thickness": 20,
                "color": "grey",
            },
            link=links,
        )
    )
    fig.show()
