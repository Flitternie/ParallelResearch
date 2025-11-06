import json
from typing import Dict, List, Any, Optional, TypedDict
from datetime import datetime
import re
from dataclasses import dataclass, field

from visualization.visualizer import BaseResearchVisualizer

@dataclass
class VisualizationConfigD3:
    """Configuration options for the D3.js tree visualization"""
    # Network dimensions
    width: int = 1200
    height: int = 800
    margin: Dict[str, int] = field(default_factory=lambda: {"top": 20, "right": 20, "bottom": 20, "left": 20})
    
    # Node appearance
    node_radius: int = 25
    node_font_size: int = 12
    node_stroke_width: int = 2
    node_opacity: float = 0.8
    node_hover_opacity: float = 1.0
    
    # Edge appearance
    edge_stroke_width: int = 2
    edge_opacity: float = 0.6
    edge_hover_opacity: float = 1.0
    
    # Tree layout settings
    node_size_x: int = 70  # Reduced spacing
    node_size_y: int = 100  # Reduced spacing
    
    # Animation settings
    animation_duration: int = 750
    transition_duration: int = 300
    
    # Info panel settings
    info_panel_width: int = 400
    info_panel_position: Dict[str, str] = field(default_factory=lambda: {"right": "20px", "top": "20px"})
    
    # Colors
    status_colors: Dict[str, str] = field(default_factory=lambda: {
        "started": "#ADD8E6",
        "completed": "#90EE90",
        "error": "#F08080",
        "default": "#D3D3D3",
        "terminated": "#FF0000",  # Orange for terminated research
        "cancelled": "#FFBF00",  # Yellow for cancelled research
    })
    
    # Operation colors
    operation_colors: Dict[str, str] = field(default_factory=lambda: {
        "plan": "#90EE90",  # Green for plan operations
        "research": "#FF0000",  # Red for research operations
        "agent_selection": "#87CEEB",  # Sky blue for agent selection
        "search_planning": "#FFA500",  # Orange for search planning
        "subquery_execution": "#DDA0DD",  # Plum for subquery execution
        "default": "#D3D3D3"  # Default gray
    })


class HTMLTemplatesD3:
    """HTML templates for D3.js visualization components"""
    
    @staticmethod
    def get_base_template() -> str:
        return '''<!DOCTYPE html>
<html>
<head>
    <title>Research Process Visualization - D3.js</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {{
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
            overflow: hidden;
        }}
        #visualization {{
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: grab;
        }}
        #visualization:active {{
            cursor: grabbing;
        }}
        #info-panel {{
            display: none;
            position: fixed;
            right: 20px;
            top: 20px;
            width: 400px;
            max-height: 80vh;
            overflow-y: auto;
            background: white;
            padding: 20px;
            border-radius: 8px;
            box-shadow: 2px 2px 10px rgba(0,0,0,0.2);
            z-index: 1000;
            transition: all 0.3s ease;
        }}
        .close-btn {{
            position: absolute;
            right: 10px;
            top: 10px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 20px;
            color: #666;
        }}
        .close-btn:hover {{
            color: #000;
        }}
        .node-label {{
            font-size: 12px;
            font-weight: bold;
            text-anchor: middle;
            pointer-events: none;
        }}
        .link {{
            stroke: #999;
            stroke-opacity: 0.6;
            transition: stroke-opacity 0.3s ease;
        }}
        .link:hover {{
            stroke-opacity: 1.0;
        }}
        .node {{
            cursor: pointer;
            transition: all 0.3s ease;
        }}
        .node:hover {{
            stroke-width: 3px;
        }}
        .tooltip {{
            position: absolute;
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 8px 12px;
            border-radius: 4px;
            font-size: 12px;
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.3s ease;
            z-index: 1001;
        }}
        .zoom-controls {{
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: white;
            border-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            padding: 5px;
        }}
        .query-boxes text {{
            user-select: text;
            cursor: text;
        }}
        .query-boxes rect {{
            filter: drop-shadow(0 2px 4px rgba(0,0,0,0.1));
        }}
        .zoom-btn {{
            display: block;
            width: 30px;
            height: 30px;
            margin: 2px;
            border: 1px solid #ccc;
            background: white;
            cursor: pointer;
            font-size: 16px;
            border-radius: 3px;
        }}
        .zoom-btn:hover {{
            background: #f0f0f0;
        }}
    </style>
</head>
<body>
    <div id="visualization">
        <div class="zoom-controls">
            <button class="zoom-btn" onclick="zoomIn()" title="Zoom In">+</button>
            <button class="zoom-btn" onclick="zoomOut()" title="Zoom Out">−</button>
            <button class="zoom-btn" onclick="resetZoom()" title="Reset Zoom">⌂</button>
        </div>
    </div>
    <div id="info-panel">
        <button class="close-btn" onclick="closeInfoPanel()">×</button>
        <div id="info-content"></div>
    </div>
    <script>
        {d3_script}
    </script>
</body>
</html>'''


class ResearchVisualizer(BaseResearchVisualizer):
    def __init__(self, log_file: str = "research_progress.json", config: Optional[VisualizationConfigD3] = None):
        self.log_file = log_file
        self.config = config or VisualizationConfigD3()
        self.templates = HTMLTemplatesD3()

    def _create_node_info_html(self, node: Dict[str, Any]) -> str:
        """Create detailed HTML information for a node"""
        details_html = f'''
        <h3>Query {node['id']} Details</h3>
        <div style="margin-bottom: 15px;">
            <b>Status:</b> <span style="color: {self.config.status_colors.get(node['status'], self.config.status_colors['default'])}">{node['status'].upper()}</span><br>
            <b>Depth:</b> {node['depth']}<br>'''

        if node.get("operation"):
            details_html += f'            <b>Operation:</b> {node["operation"].replace("_", " ").title()}<br>'

        if node.get("concurrent_group"):
            details_html += f'            <b>Concurrent Group:</b> {node["concurrent_group"]}<br>'
            
        if node.get("start_time"):
            start_time = datetime.fromisoformat(node["start_time"]).strftime("%Y-%m-%d %H:%M:%S")
            details_html += f'            <b>Start Time:</b> {start_time}<br>'
            
        if node.get("duration"):
            details_html += f'            <b>Duration:</b> {node["duration"]}<br>'

        # Handle special operations
        if node.get("operation") == "agent_selection" and node.get("results"):
            details_html += self._format_agent_selection_html(node["results"])
        elif node.get("operation") == "search_planning" and node.get("results"):
            details_html += self._format_search_planning_html(node["results"])
        elif node.get("operation") == "subquery_execution" and node.get("results"):
            details_html += self._format_subquery_execution_html(node["results"], node)
        elif node.get("operation") == "plan":
            # Handle plan operations with special query parsing
            query = self._clean_text(node['query'])
            
            if "Initial Query:" in query:
                parsed_query = self._parse_initial_query(query)
                details_html += self._format_initial_query_html(parsed_query)
            elif "Previous research goal:" in query:
                parsed_query = self._parse_research_goal(query)
                details_html += self._format_research_goal_html(parsed_query)
            else:
                details_html += f'''
            <b>Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{query}</div>
'''
            
            # Add results formatting for plan operations
            if node.get("results"):
                details_html += self._format_results_html(node["results"])
        else:
            # Handle regular queries
            query = self._clean_text(node['query'])
            
            if "Initial Query:" in query:
                parsed_query = self._parse_initial_query(query)
                details_html += self._format_initial_query_html(parsed_query)
            elif "Previous research goal:" in query:
                parsed_query = self._parse_research_goal(query)
                details_html += self._format_research_goal_html(parsed_query)
            else:
                details_html += f'''
            <b>Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">{query}</div>
'''

        if node.get("results") and node.get("operation") not in ["agent_selection", "search_planning", "subquery_execution", "plan"]:
            details_html += self._format_results_html(node["results"])

        details_html += '''
        </div>
'''
        return details_html

    def _generate_d3_script(self, nodes: List[Dict[str, Any]], edges: List[Dict[str, Any]]) -> str:
        """Generate the D3.js script for the tree visualization"""
        config = self.config
        
        # Create node info mapping
        node_info_map = {}
        for node in nodes:
            node_info_map[node['id']] = self._create_node_info_html(node)
        
        # Also add internal nodes to the info mapping
        for node in nodes:
            if node.get('internal_nodes'):
                for internal_node in node['internal_nodes']:
                    node_info_map[internal_node['id']] = self._create_node_info_html(internal_node)
        
        d3_script = f"""
        // Configuration
        const config = {{
            width: {config.width},
            height: {config.height},
            margin: {json.dumps(config.margin)},
            nodeRadius: {config.node_radius},
            nodeFontSize: {config.node_font_size},
            nodeStrokeWidth: {config.node_stroke_width},
            nodeOpacity: {config.node_opacity},
            nodeHoverOpacity: {config.node_hover_opacity},
            edgeStrokeWidth: {config.edge_stroke_width},
            edgeOpacity: {config.edge_opacity},
            edgeHoverOpacity: {config.edge_hover_opacity},
            nodeSizeX: {config.node_size_x},
            nodeSizeY: {config.node_size_y},
            animationDuration: {config.animation_duration},
            transitionDuration: {config.transition_duration}
        }};

        // Data
        const graphData = {{
            nodes: {json.dumps(nodes)},
            links: {json.dumps(edges)}
        }};

        // Node info mapping
        const nodeInfoMap = {json.dumps(node_info_map)};

        // Color scales
        const statusColors = {json.dumps(config.status_colors)};
        const operationColors = {json.dumps(config.operation_colors)};

        // Expansion state tracking
        const expandedNodes = new Set();
        const internalNodeGroups = new Map(); // Store internal node group references
        // Store internal node links
        const internalLinkGroups = new Map();
        // Will store query boxes reference
        let queryBoxes = null;

        // Setup SVG
        const svg = d3.select("#visualization")
            .append("svg")
            .attr("width", config.width)
            .attr("height", config.height);

        // Add arrowhead marker definition
        const defs = svg.append("defs");
        defs.append("marker")
            .attr("id", "arrowhead")
            .attr("viewBox", "-0 -5 10 10")
            .attr("refX", 8)
            .attr("refY", 0)
            .attr("orient", "auto")
            .attr("markerWidth", 6)
            .attr("markerHeight", 6)
            .attr("overflow", "visible")
            .append("path")
            .attr("d", "M 0,-5 L 10,0 L 0,5")
            .attr("fill", "#999")
            .style("stroke", "none");

        // Add zoom behavior
        const zoom = d3.zoom()
            .scaleExtent([0.1, 4])
            .on("zoom", function(event) {{
                g.attr("transform", event.transform);
            }});

        svg.call(zoom);

        // Create a group for all elements that will be transformed
        const g = svg.append("g");

        // Create tooltip
        const tooltip = d3.select("body")
            .append("div")
            .attr("class", "tooltip");

        // Convert flat data to hierarchical structure
        function buildHierarchy(nodes, links) {{
            const nodeMap = new Map();
            const childrenMap = new Map();
            
            // Initialize node map and children map
            nodes.forEach(function(node) {{
                nodeMap.set(node.id, {{...node, children: []}});
                childrenMap.set(node.id, []);
            }});
            
            // Build parent-child relationships
            links.forEach(function(link) {{
                const parentId = link.source;
                const childId = link.target;
                if (childrenMap.has(parentId)) {{
                    childrenMap.get(parentId).push(childId);
                }}
            }});
            
            // Find root nodes (nodes with no parents)
            const allChildren = new Set();
            links.forEach(function(link) {{ allChildren.add(link.target); }});
            
            const rootNodes = nodes.filter(function(node) {{ return !allChildren.has(node.id); }});
            
            // Build tree structure
            function buildTree(nodeId) {{
                const node = nodeMap.get(nodeId);
                if (!node) return null;
                
                const children = childrenMap.get(nodeId) || [];
                node.children = children
                    .map(function(childId) {{ return buildTree(childId); }})
                    .filter(function(child) {{ return child !== null; }});
                
                return node;
            }}
            
            // If no clear root, use the first node as root
            if (rootNodes.length === 0 && nodes.length > 0) {{
                return buildTree(nodes[0].id);
            }}
            
            // If multiple roots, create a virtual root
            if (rootNodes.length > 1) {{
                const virtualRoot = {{
                    id: "virtual_root",
                    label: "Research Process",
                    children: rootNodes.map(function(node) {{ return buildTree(node.id); }}).filter(function(node) {{ return node !== null; }})
                }};
                return virtualRoot;
            }}
            
            return buildTree(rootNodes[0].id);
        }}

        // Build the tree data
        const treeData = buildHierarchy(graphData.nodes, graphData.links);
        
        // Create tree layout with separation function for better balance
        const treeLayout = d3.tree()
            .size([config.width - 100, config.height - 100])
            .nodeSize([config.nodeSizeX * 1.5, config.nodeSizeY * 1.2])
            .separation((a, b) => a.parent === b.parent ? 1.2 : 1.5);

        // Create hierarchy and apply initial tree layout
        const root = d3.hierarchy(treeData);
        treeLayout(root);

        // Calculate bounds of all nodes for initial centering
        const allNodes = root.descendants();
        const xExtent = d3.extent(allNodes, d => d.x);
        const yExtent = d3.extent(allNodes, d => d.y);
        
        // Calculate center and scale to fit the view
        const centerX = (xExtent[0] + xExtent[1]) / 2;
        const centerY = (yExtent[0] + yExtent[1]) / 2;
        const width = xExtent[1] - xExtent[0];
        const height = yExtent[1] - yExtent[0];
        
        // Calculate scale to fit the content with some padding
        const padding = 50;
        const scaleX = (config.width - padding * 2) / (width || 1);
        const scaleY = (config.height - padding * 2) / (height || 1);
        const scale = Math.min(scaleX, scaleY, 1); // Don't scale up beyond 1
        
        // Calculate translation to center the tree
        const translateX = config.width / 2 - centerX * scale;
        const translateY = config.height / 2 - centerY * scale;
        
        // Apply initial transform
        const initialTransform = d3.zoomIdentity
            .translate(translateX, translateY)
            .scale(scale);
        
        svg.call(zoom.transform, initialTransform);

        // Create force simulation - disabled for static tree layout
        // We'll use pure tree layout for cleaner, more balanced appearance
        const simulation = null; // Removed force simulation for cleaner tree structure

        // Since we're not using simulation, we don't need ticked function
        // Positions are set directly from tree layout

        // No simulation to reheat - tree layout is static

        // Create links with elbow connector for cleaner appearance
        const link = g.append("g")
            .attr("stroke", "#999")
            .attr("stroke-opacity", config.edgeOpacity)
            .attr("stroke-width", config.edgeStrokeWidth)
            .attr("fill", "none")
            .selectAll("path")
            .data(root.links())
            .join("path")
            .attr("d", d => {{
                // Use elbow connector for cleaner tree appearance
                const sourceX = d.source.x;
                const sourceY = d.source.y;
                const targetX = d.target.x;
                const targetY = d.target.y;
                const midY = (sourceY + targetY) / 2;
                return `M${{sourceX}},${{sourceY}}C${{sourceX}},${{midY}} ${{targetX}},${{midY}} ${{targetX}},${{targetY}}`;
            }})
            .attr("class", "link");

        // Create nodes
        const node = g.append("g")
            .attr("stroke", "#fff")
            .attr("stroke-width", config.nodeStrokeWidth)
            .selectAll("g")
            .data(root.descendants())
            .join("g")
            .attr("class", "node")
            .attr("data-id", function(d) {{ return d.data.id; }})
            .attr("transform", function(d) {{ return `translate(${{d.x}}, ${{d.y}})`; }});

        // Add circles for non-expanded nodes and rectangles for expanded nodes
        node.each(function(d) {{
            const nodeGroup = d3.select(this);
            
            // Always create circle for main nodes (internal nodes are handled separately)
            nodeGroup.append("circle")
                .attr("r", function() {{
                    if (d.data.has_internal_nodes) {{
                        return config.nodeRadius * 1.2;
                    }}
                    return config.nodeRadius;
                }})
                .style("fill", function() {{
                    if (d.data.id === "virtual_root") return "#f0f0f0";
                    let color = operationColors[d.data.operation] || operationColors.default;
                    if (color === operationColors.default || d.data.status === "terminated" || d.data.status === "cancelled") {{
                        color = statusColors[d.data.status] || statusColors.default;
                    }}
                    return color;
                }})
                .style("opacity", function() {{
                    return d.data.id === "virtual_root" ? 0.3 : config.nodeOpacity;
                }})
                .style("stroke", "#fff")
                .style("stroke-width", config.nodeStrokeWidth);
        }});

        // Add expansion indicators for nodes with internal nodes
        const expansionIndicator = g.append("g")
            .attr("class", "expansion-indicators")
            .selectAll("text")
            .data(root.descendants().filter(function(d) {{ return d.data.has_internal_nodes; }}))
            .join("text")
            .attr("x", function(d) {{ return d.x + config.nodeRadius * 0.8; }})
            .attr("y", function(d) {{ return d.y - config.nodeRadius * 0.8; }})
            .style("font-size", "16px")
            .style("font-weight", "bold")
            .style("fill", function(d) {{ return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; }})
            .style("pointer-events", "none")
            .style("text-shadow", "1px 1px 2px rgba(255,255,255,0.8)")
            .text(function(d) {{ return expandedNodes.has(d.data.id) ? "−" : "+"; }});

        // Add node labels
        const label = g.append("g")
            .attr("class", "labels")
            .selectAll("text")
            .data(root.descendants())
            .join("text")
            .attr("class", "node-label")
            .attr("x", function(d) {{ return d.x; }})
            .attr("y", function(d) {{ return d.y + config.nodeRadius + 15; }})
            .style("font-size", config.nodeFontSize + "px")
            .style("text-anchor", "middle")
            .style("pointer-events", "none")
            .text(function(d) {{ return d.data.id === "virtual_root" ? "" : d.data.label; }});

        // Add query boxes near nodes (only for research operation nodes)
        queryBoxes = g.append("g")
            .attr("class", "query-boxes")
            .selectAll("g")
            .data(root.descendants().filter(d => d.data.id !== "virtual_root" && d.data.operation === "research"))
            .join("g")
            .attr("transform", d => `translate(${{d.x + config.nodeRadius + 15}}, ${{d.y - 20}})`);

        // Add background rectangles for query boxes (size calculated after text processing)
        queryBoxes.each(function(d) {{
            const queryBox = d3.select(this);
            const query = d.data.query || "";
            const words = query.split(/\s+/);
            const maxCharsPerLine = 35;
            const lineHeight = 14;
            const captionHeight = 18; // Space for caption
            const padding = 16; // 8px on each side
            
            // Calculate text lines
            let currentLine = "";
            let lines = [];
            
            words.forEach(word => {{
                if ((currentLine + " " + word).length > maxCharsPerLine) {{
                    if (currentLine) {{
                        lines.push(currentLine);
                        currentLine = word;
                    }}
                }} else {{
                    currentLine = currentLine ? currentLine + " " + word : word;
                }}
            }});
            if (currentLine) lines.push(currentLine);
            
            // Calculate adaptive dimensions
            const maxLineLength = Math.max(...lines.map(line => line.length), 13); // Min width for "Research Node"
            const boxWidth = Math.max(120, maxLineLength * 6.5 + padding); // Approx 6.5px per char + padding
            const boxHeight = Math.max(35, lines.length * lineHeight + captionHeight + 8); // 8px bottom padding
            
            // Store dimensions for later use
            d.boxWidth = boxWidth;
            d.boxHeight = boxHeight;
            d.textLines = lines;
            
            // Add background rectangle
            queryBox.append("rect")
                .attr("x", 0)
                .attr("y", 0)
                .attr("width", boxWidth)
                .attr("height", boxHeight)
                .attr("rx", 4)
                .attr("ry", 4)
                .style("fill", "white")
                .style("stroke", "#ddd")
                .style("stroke-width", 1)
                .style("opacity", 0.95);

            // Add "Research Node" caption at the top of each box
            queryBox.append("text")
                .attr("x", boxWidth / 2)
                .attr("y", 12)
                .style("font-size", "10px")
                .style("font-weight", "bold")
                .style("text-anchor", "middle")
                .style("fill", "#666")
                .text("Research Node");
        }});

        // Add query text using pre-calculated lines
        queryBoxes.each(function(d) {{
            const queryBox = d3.select(this);
            const lines = d.textLines || [];
            const lineHeight = 14;
            
            // Add text lines (starting after the caption)
            lines.forEach((line, i) => {{
                queryBox.append("text")
                    .attr("x", 8)
                    .attr("y", 26 + i * lineHeight)
                    .style("font-size", "10px")
                    .style("fill", "#333")
                    .text(line);
            }});
        }});

        // Node interactions
        node.on("mouseover", function(event, d) {{
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle, rect")
                .style("opacity", config.nodeHoverOpacity)
                .style("stroke-width", config.nodeStrokeWidth + 2);
            
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0.9);
            tooltip.html(d.data.title || d.data.query || "Node " + d.data.id)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 28) + "px");
        }})
        .on("mouseout", function(event, d) {{
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle, rect")
                .style("opacity", config.nodeOpacity)
                .style("stroke-width", config.nodeStrokeWidth);
            
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0);
        }})
        .on("click", function(event, d) {{
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            console.log("Node clicked:", d.data.id, "Has internal nodes:", d.data.has_internal_nodes, "Internal nodes:", d.data.internal_nodes);
            
            // Toggle expansion state for nodes with internal nodes
            if (d.data.has_internal_nodes) {{
                const isExpanded = expandedNodes.has(d.data.id);
                console.log("Expansion state:", isExpanded);
                
                if (isExpanded) {{
                    expandedNodes.delete(d.data.id);
                    hideInternalNodes(d);
                    console.log("Collapsed node:", d.data.id);
                }} else {{
                    expandedNodes.add(d.data.id);
                    showInternalNodes(d);
                    console.log("Expanded node:", d.data.id);
                }}
                
                // Update node shape and size
                updateNodeShape(d);
                
                // Update query box visibility for expanded node (only for research nodes)
                if (d.data.operation === "research") {{
                    queryBoxes.filter(boxData => boxData === d)
                        .style("display", isExpanded ? "none" : "block");
                }}
            }}
            
            showNodeInfo(d.data);
        }})
        .call(drag(root));

        // Link interactions
        link.on("mouseover", function() {{
            d3.select(this)
                .attr("stroke-opacity", config.edgeHoverOpacity)
                .attr("stroke-width", config.edgeStrokeWidth + 1);
        }})
        .on("mouseout", function() {{
            d3.select(this)
                .attr("stroke-opacity", config.edgeOpacity)
                .attr("stroke-width", config.edgeStrokeWidth);
        }});

        // Drag functions
        function drag(root) {{
            function dragstarted(event, d) {{
                // Prevent zoom when dragging nodes
                event.sourceEvent.stopPropagation();
            }}

            function dragged(event, d) {{
                d.x = event.x;
                d.y = event.y;
                
                // Update links with elbow connector
                link.filter(linkData => linkData.source === d || linkData.target === d)
                    .attr("d", linkData => {{
                        const sourceX = linkData.source.x;
                        const sourceY = linkData.source.y;
                        const targetX = linkData.target.x;
                        const targetY = linkData.target.y;
                        const midY = (sourceY + targetY) / 2;
                        return `M${{sourceX}},${{sourceY}}C${{sourceX}},${{midY}} ${{targetX}},${{midY}} ${{targetX}},${{targetY}}`;
                    }});
                
                // Update node position
                d3.select(this).attr("transform", `translate(${{d.x}}, ${{d.y}})`);
                
                // Update label
                label.filter(labelData => labelData === d)
                    .attr("x", d.x)
                    .attr("y", d.y + config.nodeRadius + 15);
                
                // Update query box (only for research nodes)
                if (d.data.operation === "research") {{
                    queryBoxes.filter(boxData => boxData === d)
                        .attr("transform", `translate(${{d.x + config.nodeRadius + 15}}, ${{d.y - 20}})`);
                }}
                
                // Update expansion indicator
                g.selectAll(".expansion-indicators text")
                    .filter(indicatorData => indicatorData === d)
                    .attr("x", d.x + config.nodeRadius * 0.8)
                    .attr("y", d.y - config.nodeRadius * 0.8);
            }}

            function dragended(event, d) {{
                // No simulation to update
            }}

            return d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended);
        }}

        // Show node info panel
        function showNodeInfo(node) {{
            const infoPanel = document.getElementById("info-panel");
            const infoContent = document.getElementById("info-content");
            
            if (nodeInfoMap[node.id]) {{
                infoContent.innerHTML = nodeInfoMap[node.id];
                infoPanel.style.display = "block";
            }}
        }}

        // Close info panel
        function closeInfoPanel() {{
            document.getElementById("info-panel").style.display = "none";
        }}

        // Update node shape when expanding/collapsing
        function updateNodeShape(nodeData) {{
            // Update expansion indicator
            const expansionIndicator = g.selectAll(".expansion-indicators text")
                .filter(function(d) {{ return d.data.id === nodeData.data.id; }});
            
            expansionIndicator.text(function(d) {{ 
                return expandedNodes.has(d.data.id) ? "−" : "+"; 
            }})
            .style("fill", function(d) {{ 
                return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; 
            }});
            
            // Note: We no longer change the main node shape, as internal nodes are in a separate container
        }}

        // Show internal nodes for an expanded parent
        function showInternalNodes(parentNode) {{
            if (!parentNode.data.internal_nodes || parentNode.data.internal_nodes.length === 0) return;
            
            const parentX = parentNode.x;
            const parentY = parentNode.y;
            const internalNodeCount = parentNode.data.internal_nodes.length;
            
            // Calculate container size based on number of internal nodes
            const minWidth = 200;
            const minHeight = 150;
            const padding = 20;
            const nodeSpacing = 40;
            
            // Calculate grid dimensions
            const cols = Math.min(4, Math.ceil(Math.sqrt(internalNodeCount))); // Max 4 columns
            const rows = Math.ceil(internalNodeCount / cols);
            
            const containerWidth = Math.max(minWidth, cols * nodeSpacing + padding * 2);
            const containerHeight = Math.max(minHeight, rows * nodeSpacing + padding * 2 + 30); // Extra space for title
            
            // Create internal node group
            const internalNodeGroup = g.append("g")
                .attr("class", "internal-nodes-" + parentNode.data.id)
                .attr("transform", `translate(${{parentX}}, ${{parentY}})`);
            
            // Create container background
            const container = internalNodeGroup.append("rect")
                .attr("class", "internal-container")
                .attr("x", -containerWidth / 2)
                .attr("y", -containerHeight / 2)
                .attr("width", containerWidth)
                .attr("height", containerHeight)
                .attr("rx", 8)
                .attr("ry", 8)
                .style("fill", "#f8f9fa")
                .style("stroke", "#6c757d")
                .style("stroke-width", 2)
                .style("opacity", 0.95)
                .style("cursor", "pointer")
                .on("mouseover", function() {{
                    d3.select(this)
                        .style("fill", "#e9ecef")
                        .style("stroke", "#495057")
                        .style("stroke-width", 3);
                }})
                .on("mouseout", function() {{
                    d3.select(this)
                        .style("fill", "#f8f9fa")
                        .style("stroke", "#6c757d")
                        .style("stroke-width", 2);
                }})
                .on("click", function(event) {{
                    event.stopPropagation();
                    // Collapse the expanded node
                    expandedNodes.delete(parentNode.data.id);
                    hideInternalNodes(parentNode);
                    updateNodeShape(parentNode);
                    console.log("Collapsed node via container click:", parentNode.data.id);
                }});
            
            // Add container title
            const containerTitle = internalNodeGroup.append("text")
                .attr("class", "container-title")
                .attr("x", 0)
                .attr("y", -containerHeight / 2 + 15)
                .style("text-anchor", "middle")
                .style("font-size", "12px")
                .style("font-weight", "bold")
                .style("fill", "#495057")
                .style("pointer-events", "none")
                .text(`Query ${{parentNode.data.id}}`);

            // Calculate positions for internal nodes within the container
            const startX = -containerWidth / 2 + padding + nodeSpacing / 2;
            const startY = -containerHeight / 2 + padding + 25 + nodeSpacing / 2; // Account for title
            
            // Create mapping of internal nodes by their IDs with positions inside container
            const internalNodesById = new Map();
            
            // Build hierarchical structure for internal nodes
            function buildInternalHierarchy(internalNodes, edges) {{
                const nodeMap = new Map();
                const childrenMap = new Map();
                
                // Initialize node map
                internalNodes.forEach(node => {{
                    nodeMap.set(node.id, {{...node, children: []}});
                    childrenMap.set(node.id, []);
                }});
                
                // Build parent-child relationships from edges
                if (edges) {{
                    edges.forEach(edge => {{
                        const parentId = edge.source;
                        const childId = edge.target;
                        if (childrenMap.has(parentId)) {{
                            childrenMap.get(parentId).push(childId);
                        }}
                    }});
                }}
                
                // Find root nodes (nodes with no incoming edges)
                const hasParent = new Set();
                if (edges) {{
                    edges.forEach(edge => hasParent.add(edge.target));
                }}
                
                const rootNodes = internalNodes.filter(node => !hasParent.has(node.id));
                
                // Build tree structure
                function buildSubtree(nodeId) {{
                    const node = nodeMap.get(nodeId);
                    if (!node) return null;
                    
                    const children = childrenMap.get(nodeId) || [];
                    node.children = children
                        .map(childId => buildSubtree(childId))
                        .filter(child => child !== null);
                    
                    return node;
                }}
                
                // If no clear hierarchy, arrange in sequence
                if (rootNodes.length === 0 || !edges || edges.length === 0) {{
                    return null;
                }}
                
                // Build trees from root nodes
                return rootNodes.map(root => buildSubtree(root.id)).filter(tree => tree !== null);
            }}
            
            // Try to build hierarchical layout
            const hierarchyTrees = buildInternalHierarchy(parentNode.data.internal_nodes, parentNode.data.internal_edges);
            
            if (hierarchyTrees && hierarchyTrees.length > 0) {{
                // Use hierarchical tree layout
                const availableWidth = containerWidth - padding * 2;
                const availableHeight = containerHeight - padding * 2 - 30; // Account for title
                
                // Create a tree layout for each root
                const treeLayout = d3.tree()
                    .size([availableWidth, availableHeight]);
                
                hierarchyTrees.forEach((treeRoot, treeIndex) => {{
                    const hierarchy = d3.hierarchy(treeRoot);
                    const treeNodes = treeLayout(hierarchy);
                    
                    // Calculate tree width for positioning
                    const treeWidth = availableWidth / hierarchyTrees.length;
                    const treeStartX = treeIndex * treeWidth;
                    
                    // Position nodes in this tree (relative to container origin)
                    treeNodes.descendants().forEach(node => {{
                        const nodeX = treeStartX + (node.x - availableWidth/2) * 0.8; // Scale down a bit
                        const nodeY = node.y * 0.8; // Scale down vertically
                        
                        internalNodesById.set(node.data.id, {{
                            ...node.data,
                            x: nodeX,
                            y: nodeY,
                            treeIndex: treeIndex,
                            depth: node.depth
                        }});
                    }});
                }});
            }} else {{
                // Fallback to grid layout if no clear hierarchy
                parentNode.data.internal_nodes.forEach((node, index) => {{
                    const cols = Math.min(4, Math.ceil(Math.sqrt(internalNodeCount)));
                    const rows = Math.ceil(internalNodeCount / cols);
                    const col = index % cols;
                    const row = Math.floor(index / cols);
                    
                    // Position relative to container origin (will be centered later)
                    const nodeX = col * nodeSpacing - (cols - 1) * nodeSpacing / 2;
                    const nodeY = row * nodeSpacing - (rows - 1) * nodeSpacing / 2;
                    
                    internalNodesById.set(node.id, {{
                        ...node,
                        x: nodeX,
                        y: nodeY
                    }});
                }});
            }}
            
            // Auto-center all nodes within the container
            const allNodes = Array.from(internalNodesById.values());
            if (allNodes.length > 0) {{
                // Calculate bounds of positioned nodes
                const bounds = {{
                    minX: Math.min(...allNodes.map(n => n.x)),
                    maxX: Math.max(...allNodes.map(n => n.x)),
                    minY: Math.min(...allNodes.map(n => n.y)),
                    maxY: Math.max(...allNodes.map(n => n.y))
                }};
                
                // Calculate center offset to center the group within available space
                const contentWidth = bounds.maxX - bounds.minX;
                const contentHeight = bounds.maxY - bounds.minY;
                const contentCenterX = (bounds.minX + bounds.maxX) / 2;
                const contentCenterY = (bounds.minY + bounds.maxY) / 2;
                
                const availableWidth = containerWidth - padding * 2;
                const availableHeight = containerHeight - padding * 2 - 30;
                
                // Center the content within available space
                const offsetX = -contentCenterX;
                const offsetY = -contentCenterY + 10; // Small offset from top for better visual balance
                
                // Apply centering offset to all nodes
                allNodes.forEach(node => {{
                    node.x += offsetX;
                    node.y += offsetY;
                }});
            }}

            // Process internal links
            const internalLinks = [];
            if (parentNode.data.internal_edges) {{
                console.log("Processing internal edges for node", parentNode.data.id, ":", parentNode.data.internal_edges);
                parentNode.data.internal_edges.forEach(edge => {{
                    const sourceNode = internalNodesById.get(edge.source);
                    const targetNode = internalNodesById.get(edge.target);
                    console.log("Edge:", edge.source, "->", edge.target, "Source found:", !!sourceNode, "Target found:", !!targetNode);
                    if (sourceNode && targetNode) {{
                        internalLinks.push({{
                            source: sourceNode,
                            target: targetNode,
                            sourceId: edge.source,
                            targetId: edge.target
                        }});
                    }}
                }});
                console.log("Created", internalLinks.length, "internal links for node", parentNode.data.id);
            }} else {{
                console.log("No internal edges found for node", parentNode.data.id);
            }}

            // Create links between internal nodes (relative to container)
            const linkGroup = internalNodeGroup.append("g")
                .attr("class", "internal-links");

            const linkPaths = linkGroup.selectAll("path")
                .data(internalLinks)
                .join("path")
                .attr("d", d => {{
                    // Use curved links for tree-like appearance when we have hierarchy
                    if (d.source.depth !== undefined && d.target.depth !== undefined) {{
                        // Tree-style curved link
                        const sourceX = d.source.x;
                        const sourceY = d.source.y;
                        const targetX = d.target.x;
                        const targetY = d.target.y;
                        const midY = (sourceY + targetY) / 2;
                        return `M${{sourceX}},${{sourceY}}C${{sourceX}},${{midY}} ${{targetX}},${{midY}} ${{targetX}},${{targetY}}`;
                    }} else {{
                        // Straight line for grid layout
                        return `M${{d.source.x}},${{d.source.y}}L${{d.target.x}},${{d.target.y}}`;
                    }}
                }})
                .style("fill", "none")
                .style("stroke", "#6c757d")
                .style("stroke-width", 1.5)
                .style("stroke-opacity", 0.7)
                .style("marker-end", "url(#arrowhead)")
                .on("mouseover", function() {{
                    d3.select(this)
                        .style("stroke-opacity", 1)
                        .style("stroke-width", 2.5)
                        .style("stroke", "#dc3545");
                }})
                .on("mouseout", function() {{
                    d3.select(this)
                        .style("stroke-opacity", 0.7)
                        .style("stroke-width", 1.5)
                        .style("stroke", "#6c757d");
                }});

            // Add internal nodes (relative to container)
            const nodeCircles = internalNodeGroup.selectAll("circle")
                .data(Array.from(internalNodesById.values()))
                .join("circle")
                .attr("r", config.nodeRadius * 0.35)
                .attr("cx", d => d.x)
                .attr("cy", d => d.y)
                .style("fill", d => {{
                    let color = operationColors[d.operation] || operationColors.default;
                    if (color === operationColors.default || d.status === "terminated" || d.status === "cancelled") {{
                        color = statusColors[d.status] || statusColors.default;
                    }}
                    return color;
                }})
                .style("opacity", 0.9)
                .style("stroke", "#fff")
                .style("stroke-width", 1.5)
                .style("cursor", "pointer");

            // Add node labels (relative to container)
            const nodeLabels = internalNodeGroup.selectAll(".node-label")
                .data(Array.from(internalNodesById.values()))
                .join("text")
                .attr("class", "node-label")
                .attr("x", d => d.x)
                .attr("y", d => d.y + config.nodeRadius * 0.35 + 10)
                .style("font-size", "9px")
                .style("text-anchor", "middle")
                .style("pointer-events", "none")
                .style("fill", "#495057")
                .text(d => d.id);

            // Store references for later removal and updates
            internalNodeGroups.set(parentNode.data.id, internalNodeGroup);
            internalLinkGroups.set(parentNode.data.id, linkGroup);

            // Add interactions
            nodeCircles
                .on("mouseover", function(event, d) {{
                    // Highlight connected links
                    linkPaths
                        .style("stroke-opacity", link => {{
                            if (link.sourceId === d.id || link.targetId === d.id) {{
                                return 1;
                            }}
                            return 0.2;
                        }})
                        .style("stroke-width", link => {{
                            if (link.sourceId === d.id || link.targetId === d.id) {{
                                return 2.5;
                            }}
                            return 1.5;
                        }})
                        .style("stroke", link => {{
                            if (link.sourceId === d.id || link.targetId === d.id) {{
                                return "#dc3545";
                            }}
                            return "#6c757d";
                        }});

                    d3.select(this)
                        .style("opacity", 1.0)
                        .style("stroke-width", 2.5);
                    
                    tooltip.transition()
                        .duration(config.transitionDuration)
                        .style("opacity", 0.9);
                    tooltip.html(d.query || "Internal Node " + d.id)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 28) + "px");
                }})
                .on("mouseout", function(event, d) {{
                    // Restore all links
                    linkPaths
                        .style("stroke-opacity", 0.7)
                        .style("stroke-width", 1.5)
                        .style("stroke", "#6c757d");

                    d3.select(this)
                        .style("opacity", 0.9)
                        .style("stroke-width", 1.5);
                    
                    tooltip.transition()
                        .duration(config.transitionDuration)
                        .style("opacity", 0);
                }})
                .on("click", function(event, d) {{
                    event.stopPropagation();
                    showInternalNodeInfo(d);
                }});
        }}

        // Hide internal nodes for a collapsed parent
        function hideInternalNodes(parentNode) {{
            const internalNodeGroup = internalNodeGroups.get(parentNode.data.id);
            if (internalNodeGroup) {{
                internalNodeGroup.remove();
                internalNodeGroups.delete(parentNode.data.id);
            }}
            const linkGroup = internalLinkGroups.get(parentNode.data.id);
            if (linkGroup) {{
                linkGroup.remove();
                internalLinkGroups.delete(parentNode.data.id);
            }}
        }}

        // Show info for internal nodes
        function showInternalNodeInfo(internalNode) {{
            const infoPanel = document.getElementById("info-panel");
            const infoContent = document.getElementById("info-content");
            
            // Check if we have detailed info for this internal node
            if (nodeInfoMap[internalNode.id]) {{
                infoContent.innerHTML = nodeInfoMap[internalNode.id];
            }} else {{
                // Create simplified info for internal nodes
                const internalInfo = `
                    <h3>Internal Node ${{internalNode.id}} Details</h3>
                    <div style="margin-bottom: 15px;">
                        <b>Status:</b> <span style="color: ${{statusColors[internalNode.status] || statusColors.default}}">${{internalNode.status.toUpperCase()}}</span><br>
                        <b>Parent Node:</b> ${{internalNode.parentId}}<br>
                        <b>Query:</b>
                        <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${{internalNode.query}}</div>
                    </div>
                `;
                infoContent.innerHTML = internalInfo;
            }}
            
            infoPanel.style.display = "block";
        }}

        // Make functions globally available
        window.updateNode = updateNode;
        window.addNode = addNode;
        window.removeNode = removeNode;
        window.showNodeInfo = showNodeInfo;
        window.closeInfoPanel = closeInfoPanel;
        
        // Zoom control functions
        window.zoomIn = function() {{
            svg.transition().duration(300).call(
                zoom.scaleBy, 1.5
            );
        }};
        
        window.zoomOut = function() {{
            svg.transition().duration(300).call(
                zoom.scaleBy, 1 / 1.5
            );
        }};
        
        window.resetZoom = function() {{
            // Recalculate bounds and center the view
            const allNodes = root.descendants();
            const xExtent = d3.extent(allNodes, d => d.x);
            const yExtent = d3.extent(allNodes, d => d.y);
            
            const centerX = (xExtent[0] + xExtent[1]) / 2;
            const centerY = (yExtent[0] + yExtent[1]) / 2;
            const width = xExtent[1] - xExtent[0];
            const height = yExtent[1] - yExtent[0];
            
            const padding = 50;
            const scaleX = (config.width - padding * 2) / (width || 1);
            const scaleY = (config.height - padding * 2) / (height || 1);
            const scale = Math.min(scaleX, scaleY, 1);
            
            const translateX = config.width / 2 - centerX * scale;
            const translateY = config.height / 2 - centerY * scale;
            
            const resetTransform = d3.zoomIdentity
                .translate(translateX, translateY)
                .scale(scale);
            
            svg.transition().duration(300).call(
                zoom.transform,
                resetTransform
            );
        }};

        // No need for recalculate layout function with static tree
        """
        
        return d3_script

    def visualize(self, output_file: str = "research_visualization_d3.html"):
        """Create an interactive D3.js visualization of the research progress"""
        log_data = self.load_log()
        
        # Create nodes list - exclude internal nodes from main tree
        nodes = []
        id_to_node = {str(node["id"]): node for node in log_data["nodes"].values()}

        # Build parent -> [internal nodes] mapping and collect internal edges
        parent_to_internal = {}
        internal_edges = {}  # Store edges between internal nodes by parent
        for node in log_data["nodes"].values():
            node_id_str = str(node["id"])
            # Internal node: has a dot and its parent is the part before the first dot
            if '.' in node_id_str:
                parent_id = node_id_str.split('.')[0]
                parent_to_internal.setdefault(parent_id, []).append(node)

        # Collect edges between internal nodes
        for edge in log_data["edges"]:
            source_id = str(edge["from"])
            target_id = str(edge["to"])
            
            # If both nodes are internal nodes and share the same parent
            if '.' in source_id and '.' in target_id:
                source_parent = source_id.split('.')[0]
                target_parent = target_id.split('.')[0]
                if source_parent == target_parent:
                    # Store edges with proper structure for D3
                    internal_edges.setdefault(source_parent, []).append({
                        "source": source_id,  # Changed from "from" to "source"
                        "target": target_id   # Changed from "to" to "target"
                    })

        # Only add main nodes (non-internal) to the tree structure
        for node in log_data["nodes"].values():
            node_id_str = str(node["id"])
            # Skip internal nodes - they will be shown only when parent is expanded
            if '.' in node_id_str:
                continue
                
            internal_nodes = parent_to_internal.get(node_id_str, [])
            # Add edges information to internal nodes
            node_internal_edges = internal_edges.get(node_id_str, [])
            
            # First check for operation-based color
            background_color = self.config.operation_colors.get(
                node.get("operation", "default"),
                self.config.operation_colors["default"]
            )

            if node["status"] in ["terminated", "cancelled"]:
                # If operation color is not found, use status-based coloring
                background_color = self.config.status_colors.get(
                    node["status"], 
                    self.config.status_colors["default"]
                )

            # If no operation color found, fall back to status-based coloring
            if background_color == self.config.operation_colors["default"]:
                background_color = self.config.status_colors.get(
                    node["status"], 
                    self.config.status_colors["default"]
                )
            node_data = {
                "id": node["id"],
                "label": f"Q{node['id']}",
                "title": self._clean_text(node["query"]),
                "query": self._clean_text(node["query"]),
                "color": background_color,
                "status": node["status"],
                "operation": node.get("operation", "default"),
                "depth": node.get("depth", 0),
                "breadth": node.get("breadth", 0),
                "concurrent_group": node.get("concurrent_group"),
                "results": node.get("results"),
                "start_time": node.get("start_time"),
                "duration": node.get("duration"),
                "has_internal_nodes": len(internal_nodes) > 0,
                "internal_nodes": internal_nodes,
                "internal_edges": node_internal_edges
            }
            nodes.append(node_data)

        # print(f"Total main nodes: {len(nodes)}")
        # print(f"Nodes with internal nodes: {len([n for n in nodes if n['has_internal_nodes']])}")
        # print(f"Total internal nodes: {sum(len(n['internal_nodes']) for n in nodes if n['has_internal_nodes'])}")
        
        # Create edges list - only include edges between main nodes
        edges = []
        for edge in log_data["edges"]:
            # Skip edges that involve internal nodes
            if self._is_internal_node(edge["from"]) or self._is_internal_node(edge["to"]):
                continue
            edges.append({"source": edge["from"], "target": edge["to"]})
        
        # Generate HTML content
        d3_script = self._generate_d3_script(nodes, edges)
        html_content = self.templates.get_base_template().format(d3_script=d3_script)
        
        # Save visualization
        with open(output_file, 'w') as f:
            f.write(html_content) 