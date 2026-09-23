/*
 * ADOBE CONFIDENTIAL
 *
 * Copyright 2026 Adobe
 * All Rights Reserved.
 *
 * NOTICE: All information contained herein is, and remains
 * the property of Adobe and its suppliers, if any. The intellectual
 * and technical concepts contained herein are proprietary to Adobe
 * and its suppliers and are protected by all applicable intellectual
 * property laws, including trade secret and copyright laws.
 * Dissemination of this information or reproduction of this material
 * is strictly forbidden unless prior written permission is obtained
 * from Adobe.
 */

// Configuration for D3.js visualization
class VisualizationConfigD3 {
    constructor(options = {}) {
        // Network dimensions
        this.width = options.width || 1200;
        this.height = options.height || 800;
        this.margin = options.margin || { top: 20, right: 20, bottom: 20, left: 20 };
        
        // Node appearance
        this.node_radius = options.node_radius || 25;
        this.node_font_size = options.node_font_size || 12;
        this.node_stroke_width = options.node_stroke_width || 2;
        this.node_opacity = options.node_opacity || 0.8;
        this.node_hover_opacity = options.node_hover_opacity || 1.0;
        
        // Edge appearance
        this.edge_stroke_width = options.edge_stroke_width || 2;
        this.edge_opacity = options.edge_opacity || 0.6;
        this.edge_hover_opacity = options.edge_hover_opacity || 1.0;
        
        // Tree layout settings
        this.node_size_x = options.node_size_x || 80;
        this.node_size_y = options.node_size_y || 120;
        
        // Animation settings
        this.animation_duration = options.animation_duration || 750;
        this.transition_duration = options.transition_duration || 300;
        
        // Info panel settings
        this.info_panel_width = options.info_panel_width || 400;
        this.info_panel_position = options.info_panel_position || { right: "20px", top: "20px" };
        
        // Colors
        this.status_colors = options.status_colors || {
            "started": "#ADD8E6",
            "completed": "#90EE90",
            "error": "#F08080",
            "default": "#D3D3D3",
            "terminated": "#FF8706", 
            "cancelled": "#FFBF00", 
        };
        
        // Operation colors
        this.operation_colors = options.operation_colors || {
            "plan": "#90EE90",  // Green for plan operations
            "research": "#FF0000",  // Red for research operations
            "agent_selection": "#87CEEB",  // Sky blue for agent selection
            "search_planning": "#FFA500",  // Orange for search planning
            "subquery_execution": "#DDA0DD",  // Plum for subquery execution
            "default": "#D3D3D3"  // Default gray
        };
    }
}

// HTML templates for D3.js visualization components
class HTMLTemplatesD3 {
    static getBaseTemplate() {
        return `<!DOCTYPE html>
<html>
<head>
    <title>Research Process Visualization - D3.js</title>
    <script src="https://d3js.org/d3.v7.min.js"></script>
    <style>
        body {
            font-family: Arial, sans-serif;
            margin: 0;
            padding: 0;
            background-color: #f5f5f5;
            overflow: hidden;
        }
        #visualization {
            background-color: white;
            border-radius: 8px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            cursor: grab;
        }
        #visualization:active {
            cursor: grabbing;
        }
        #info-panel {
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
        }
        .close-btn {
            position: absolute;
            right: 10px;
            top: 10px;
            border: none;
            background: none;
            cursor: pointer;
            font-size: 20px;
            color: #666;
        }
        .close-btn:hover {
            color: #000;
        }
        .node-label {
            font-size: 12px;
            font-weight: bold;
            text-anchor: middle;
            pointer-events: none;
        }
        .link {
            stroke: #999;
            stroke-opacity: 0.6;
            transition: stroke-opacity 0.3s ease;
        }
        .link:hover {
            stroke-opacity: 1.0;
        }
        .node {
            cursor: pointer;
            transition: all 0.3s ease;
        }
        .node:hover {
            stroke-width: 3px;
        }
        .tooltip {
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
        }
        .zoom-controls {
            position: absolute;
            top: 10px;
            left: 10px;
            z-index: 1000;
            background: white;
            border-radius: 4px;
            box-shadow: 0 2px 5px rgba(0,0,0,0.2);
            padding: 5px;
        }
        .zoom-btn {
            display: block;
            width: 30px;
            height: 30px;
            margin: 2px;
            border: 1px solid #ccc;
            background: white;
            cursor: pointer;
            font-size: 16px;
            border-radius: 3px;
        }
        .zoom-btn:hover {
            background: #f0f0f0;
        }
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
</html>`;
    }
}

// Base class for research visualizers with common functionality
class BaseResearchVisualizer {
    constructor(logFile = "research_progress.json") {
        this.logFile = logFile;
    }

    async loadLog() {
        try {
            // In web context, we'll receive the log data directly
            // This method will be overridden in the web implementation
            throw new Error("loadLog must be implemented by subclass");
        } catch (e) {
            throw new Error(`Error loading log file ${this.logFile}: ${e.message}`);
        }
    }

    _cleanText(text) {
        // Clean text by removing problematic characters and normalizing quotes
        text = text.replace(/[^\x20-\x7E\n'"]/g, '');
        text = text.replace(/[""]/g, '"');
        text = text.replace(/['']/g, "'");
        return text;
    }

    _parseInitialQuery(query) {
        // Parse a query that contains Initial Query and Q&A format
        let parts = query.split("Follow - up Questions and Answers:");
        if (parts.length !== 2) {
            parts = query.split("Follow-up Questions and Answers:");
            if (parts.length !== 2) {
                return { initial_query: query.trim(), qa_pairs: [] };
            }
        }

        const initialQuery = parts[0].replace("Initial Query:", "").trim();
        const qaText = parts[1].trim();

        const qaPairs = [];
        const qaParts = qaText.split("Q: ");
        for (let i = 1; i < qaParts.length; i++) {
            const part = qaParts[i];
            if (part.includes("A: ")) {
                const [q, a] = part.split("A: ", 2);
                qaPairs.push({
                    question: q.trim(),
                    answer: a.trim()
                });
            }
        }

        return {
            initial_query: initialQuery,
            qa_pairs: qaPairs
        };
    }

    _parseResearchGoal(query) {
        // Parse a query that contains Previous research goal and follow-up questions
        const sections = query.split("Follow-up questions:");
        if (sections.length !== 2) {
            return { research_goal: query.trim(), follow_up_questions: [] };
        }

        const goal = sections[0].replace("Previous research goal:", "").trim();
        const questions = sections[1].split("?").map(q => q.trim()).filter(q => q);

        return {
            research_goal: goal,
            follow_up_questions: questions
        };
    }

    _formatInitialQueryHTML(parsedQuery) {
        // Format the initial query and Q&A pairs as HTML
        let html = `
            <b>Initial Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${parsedQuery.initial_query}</div>
`;

        if (parsedQuery.qa_pairs.length > 0) {
            html += `
            <b>Follow-up Questions and Answers:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
`;
            for (const qa of parsedQuery.qa_pairs) {
                html += `
                <div style="margin-bottom: 8px;">
                    <b>Q:</b> ${qa.question}<br>
                    <b>A:</b> ${qa.answer}
                </div>`;
            }
            html += "            </div>";
        }

        return html;
    }

    _formatResearchGoalHTML(parsedQuery) {
        // Format the research goal and follow-up questions as HTML
        let html = `
            <b>Previous Research Goal:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${parsedQuery.research_goal}</div>
`;

        if (parsedQuery.follow_up_questions.length > 0) {
            html += `
            <b>Follow-up Questions:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
`;
            for (const question of parsedQuery.follow_up_questions) {
                html += `                - ${question}?<br>`;
            }
            html += "            </div>";
        }

        return html;
    }

    _formatAgentSelectionHTML(results) {
        // Format agent selection information as HTML
        let html = "";

        if (results.agent) {
            html += `
            <b>Selected Agent:</b>
            <div style="padding: 8px; background: #e8f4fd; border-radius: 4px; margin: 5px 0; border-left: 4px solid #2196F3;">
                ${this._cleanText(results.agent)}
            </div>
`;
        }

        if (results.role) {
            html += `
            <b>Agent Role:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">
                ${this._cleanText(results.role)}
            </div>
`;
        }

        return html;
    }

    _formatSearchPlanningHTML(results) {
        // Format search planning subqueries as HTML
        let html = "";

        if (results.subqueries) {
            html += `
            <b>Planned Subqueries (${results.subqueries.length}):</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
`;
            for (let i = 0; i < results.subqueries.length; i++) {
                const subquery = results.subqueries[i];
                html += `
                <div style="margin-bottom: 8px; padding: 6px; background: #fafafa; border-radius: 3px;">
                    <b>${i + 1}.</b> ${this._cleanText(subquery)}
                </div>`;
            }
            html += "            </div>";
        }

        return html;
    }

    _parseContentSections(content) {
        // Parse content text to extract Source, Title, and Content sections
        const sections = [];
        let currentSection = {};

        const lines = content.split('\n');
        for (const line of lines) {
            const trimmedLine = line.trim();
            if (!trimmedLine) continue;

            if (trimmedLine.startsWith('Source:')) {
                // Save previous section if exists
                if (Object.keys(currentSection).length > 0) {
                    sections.push(currentSection);
                }
                currentSection = { source: trimmedLine.substring(7).trim() };
            } else if (trimmedLine.startsWith('Title:')) {
                if (Object.keys(currentSection).length > 0) {
                    currentSection.title = trimmedLine.substring(6).trim();
                }
            } else if (trimmedLine.startsWith('Content:')) {
                if (Object.keys(currentSection).length > 0) {
                    currentSection.content = trimmedLine.substring(8).trim();
                }
            } else if (Object.keys(currentSection).length > 0 && currentSection.content !== undefined) {
                // Continue content from previous line
                currentSection.content += ' ' + trimmedLine;
            }
        }

        // Add the last section
        if (Object.keys(currentSection).length > 0) {
            sections.push(currentSection);
        }

        return sections;
    }

    _formatSubqueryExecutionHTML(results, node) {
        // Format subquery execution information as HTML
        let html = "";

        // Display the subquery query
        if (node.query) {
            html += `
            <b>Subquery:</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
                ${this._cleanText(node.query)}
            </div>
`;
        }

        if (results.content) {
            // Parse the content into sections
            const sections = this._parseContentSections(results.content);

            if (sections.length > 0) {
                html += `
            <b>Research Summary (${sections.length} sources):</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
`;
                for (let i = 0; i < sections.length; i++) {
                    const section = sections[i];
                    html += `
                <div style="margin-bottom: 12px; padding: 8px; background: #f8f9fa; border-radius: 4px; border-left: 3px solid #28a745;">
                    <b>Source ${i + 1}:</b><br>
                    <small style="color: #6c757d;">${this._cleanText(section.source || '')}</small><br><br>
`;

                    if (section.title) {
                        html += `
                    <b>Title:</b> ${this._cleanText(section.title)}<br><br>
`;
                    }

                    if (section.content) {
                        // Truncate content if too long
                        let content = this._cleanText(section.content);
                        if (content.length > 300) {
                            content = content.substring(0, 300) + "...";
                        }
                        html += `
                    <b>Content:</b> ${content}
`;
                    }

                    html += "                </div>";
                }

                html += "            </div>";
            } else {
                // Fallback if parsing fails
                html += `
            <b>Research Summary:</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
                ${this._cleanText(results.content)}
            </div>
`;
            }
        }

        if (results.scraped_data && results.scraped_data.length > 0) {
            html += `
            <b>Sources (${results.scraped_data.length}):</b>
            <div style="padding: 8px; background: #f0f8ff; border-radius: 4px; margin: 5px 0; border-left: 4px solid #2196F3;">
`;
            for (let i = 0; i < results.scraped_data.length; i++) {
                const source = results.scraped_data[i];
                const title = this._cleanText(source.title || "Untitled");
                const url = this._cleanText(source.url || "");
                html += `
                <div style="margin-bottom: 6px; padding: 4px; background: #fafafa; border-radius: 3px;">
                    <b>${i + 1}.</b> ${title}<br>
                    <small><a href="${url}" target="_blank">${url}</a></small>
                </div>`;
            }
            html += "            </div>";
        }

        return html;
    }

    _formatResultsHTML(results) {
        // Format the results section of the node details
        let html = "";

        if (results.learnings) {
            const parsedLearnings = this._parseLearnings(results.learnings, results.citations || {});

            html += `
            <b>Key Learnings (${parsedLearnings.length}):</b>
            <div style="padding: 8px; background: #e8f5e8; border-radius: 4px; margin: 5px 0; border-left: 4px solid #4CAF50;">
`;
            for (let i = 0; i < parsedLearnings.length; i++) {
                const learning = parsedLearnings[i];
                html += `
                <div style="margin-bottom: 8px; padding: 6px; background: #f8f9fa; border-radius: 3px;">
                    <b>${i + 1}.</b> ${this._cleanText(learning.content)}`;

                if (learning.url) {
                    html += `<br>
                    <small><a href="${learning.url}" target="_blank">[Source]</a></small>`;
                }

                html += "                </div>";
            }
            html += "            </div>";
        }

        if (results.followUpQuestions) {
            html += `
            <b>Follow-up Questions (${results.followUpQuestions.length})</b>
            <div style="padding: 8px; background: #fff3e0; border-radius: 4px; margin: 5px 0; border-left: 4px solid #ff9800;">
`;
            for (let i = 0; i < results.followUpQuestions.length; i++) {
                const question = results.followUpQuestions[i];
                html += `
                <div style="margin-bottom: 6px; padding: 4px; background: #fafafa; border-radius: 3px;">
                    <b>${i + 1}.</b> ${this._cleanText(question)}
                </div>`;
            }
            html += "            </div>";
        }

        return html;
    }

    _parseLearnings(learnings, citations = {}) {
        // Parse learnings to separate URLs from content
        const parsedLearnings = [];

        for (const learning of learnings) {
            let url = citations[learning] || "";
            url = url.endsWith(':') ? url.slice(0, -1) : url;

            // Handle format 1: "Learning [content]"
            if (learning.startsWith("Learning ")) {
                const content = learning.substring(9).trim(); // Remove "Learning " prefix
                parsedLearnings.push({
                    url: url,
                    content: content
                });
            }
            // Handle format 2: "//url]: [content]"
            else if (learning.startsWith("//")) {
                // Extract URL from the beginning
                const urlEnd = learning.indexOf("]: ");
                if (urlEnd !== -1) {
                    const content = learning.substring(urlEnd + 3).trim(); // Remove "]: " and get content
                    parsedLearnings.push({
                        url: url,
                        content: content
                    });
                } else {
                    // Fallback if format is unexpected
                    parsedLearnings.push({
                        url: url,
                        content: learning.trim()
                    });
                }
            } else {
                parsedLearnings.push({
                    url: url,
                    content: learning.trim()
                });
            }
        }

        return parsedLearnings;
    }

    _isInternalNode(nodeId) {
        // Check if a node is an internal node (has format X.X or X.X.X)
        return String(nodeId).includes('.');
    }

    _getParentNodeId(internalNodeId) {
        // Get the parent node ID from an internal node ID (e.g., '1.2' -> '1')
        return String(internalNodeId).split('.')[0];
    }
}

// Main research visualizer class
class ResearchVisualizer extends BaseResearchVisualizer {
    constructor(logFile = "research_progress.json", config = null) {
        super(logFile);
        this.config = config || new VisualizationConfigD3();
        this.templates = HTMLTemplatesD3;
        this.logData = null;
        this.lastLogData = null; // Track previous data to avoid unnecessary re-renders
        this.lastResult = null; // Cache last result
    }

    // Set log data directly (for web context)
    setLogData(logData) {
        this.logData = logData;
    }

    async loadLog() {
        if (this.logData) {
            return this.logData;
        }
        throw new Error("No log data available");
    }

    _createNodeInfoHTML(node) {
        // Create detailed HTML information for a node
        let detailsHTML = `
        <h3>Query ${node.id} Details</h3>
        <div style="margin-bottom: 15px;">
            <b>Status:</b> <span style="color: ${this.config.status_colors[node.status] || this.config.status_colors.default}">${node.status.toUpperCase()}</span><br>
            <b>Depth:</b> ${node.depth}<br>`;

        if (node.operation) {
            detailsHTML += `            <b>Operation:</b> ${node.operation.replace(/_/g, " ").replace(/\b\w/g, l => l.toUpperCase())}<br>`;
        }

        if (node.concurrent_group) {
            detailsHTML += `            <b>Concurrent Group:</b> ${node.concurrent_group}<br>`;
        }

        if (node.start_time) {
            const startTime = new Date(node.start_time).toLocaleString();
            detailsHTML += `            <b>Start Time:</b> ${startTime}<br>`;
        }

        if (node.duration) {
            detailsHTML += `            <b>Duration:</b> ${node.duration}<br>`;
        }

        // Handle special operations
        if (node.operation === "agent_selection" && node.results) {
            detailsHTML += this._formatAgentSelectionHTML(node.results);
        } else if (node.operation === "search_planning" && node.results) {
            detailsHTML += this._formatSearchPlanningHTML(node.results);
        } else if (node.operation === "subquery_execution" && node.results) {
            detailsHTML += this._formatSubqueryExecutionHTML(node.results, node);
        } else if (node.operation === "plan") {
            // Handle plan operations with special query parsing
            const query = this._cleanText(node.query);

            if (query.includes("Initial Query:")) {
                const parsedQuery = this._parseInitialQuery(query);
                detailsHTML += this._formatInitialQueryHTML(parsedQuery);
            } else if (query.includes("Previous research goal:")) {
                const parsedQuery = this._parseResearchGoal(query);
                detailsHTML += this._formatResearchGoalHTML(parsedQuery);
            } else {
                detailsHTML += `
            <b>Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${query}</div>
`;
            }

            // Add results formatting for plan operations
            if (node.results) {
                detailsHTML += this._formatResultsHTML(node.results);
            }
        } else {
            // Handle regular queries
            const query = this._cleanText(node.query);

            if (query.includes("Initial Query:")) {
                const parsedQuery = this._parseInitialQuery(query);
                detailsHTML += this._formatInitialQueryHTML(parsedQuery);
            } else if (query.includes("Previous research goal:")) {
                const parsedQuery = this._parseResearchGoal(query);
                detailsHTML += this._formatResearchGoalHTML(parsedQuery);
            } else {
                detailsHTML += `
            <b>Query:</b>
            <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${query}</div>
`;
            }
        }

        if (node.results && !["agent_selection", "search_planning", "subquery_execution", "plan"].includes(node.operation)) {
            detailsHTML += this._formatResultsHTML(node.results);
        }

        detailsHTML += `
        </div>
`;
        return detailsHTML;
    }

    _generateD3Script(nodes, edges) {
        // Generate the D3.js script for the tree visualization
        const config = this.config;

        // Create node info mapping
        const nodeInfoMap = {};
        for (const node of nodes) {
            nodeInfoMap[node.id] = this._createNodeInfoHTML(node);
        }

        // Also add internal nodes to the info mapping
        for (const node of nodes) {
            if (node.internal_nodes) {
                for (const internalNode of node.internal_nodes) {
                    nodeInfoMap[internalNode.id] = this._createNodeInfoHTML(internalNode);
                }
            }
        }

        const d3Script = `
        // Configuration
        const config = ${JSON.stringify({
            width: config.width,
            height: config.height,
            margin: config.margin,
            nodeRadius: config.node_radius,
            nodeFontSize: config.node_font_size,
            nodeStrokeWidth: config.node_stroke_width,
            nodeOpacity: config.node_opacity,
            nodeHoverOpacity: config.node_hover_opacity,
            edgeStrokeWidth: config.edge_stroke_width,
            edgeOpacity: config.edge_opacity,
            edgeHoverOpacity: config.edge_hover_opacity,
            nodeSizeX: config.node_size_x,
            nodeSizeY: config.node_size_y,
            animationDuration: config.animation_duration,
            transitionDuration: config.transition_duration
        })};

        // Data
        const graphData = {
            nodes: ${JSON.stringify(nodes)},
            links: ${JSON.stringify(edges)}
        };

        // Node info mapping
        const nodeInfoMap = ${JSON.stringify(nodeInfoMap)};

        // Color scales
        const statusColors = ${JSON.stringify(config.status_colors)};
        const operationColors = ${JSON.stringify(config.operation_colors)};

        // Expansion state tracking
        const expandedNodes = new Set();
        const internalNodeGroups = new Map(); // Store internal node group references
        // Store internal node links
        const internalLinkGroups = new Map();

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
            .on("zoom", function(event) {
                g.attr("transform", event.transform);
            });

        svg.call(zoom);

        // Create a group for all elements that will be transformed
        const g = svg.append("g");
        
        // Add global mouse leave handler for the SVG to ensure tooltips are hidden
        svg.on("mouseleave", function() {
            // Find any tooltips and hide them
            d3.selectAll(".research-tooltip").transition()
                .duration(config.transitionDuration)
                .style("opacity", 0);
        });

        // Remove any existing tooltips first
        d3.selectAll(".research-tooltip").remove();
        
        // Create tooltip
        const tooltip = d3.select("body")
            .append("div")
            .attr("class", "research-tooltip")
            .style("position", "absolute")
            .style("background", "rgba(0, 0, 0, 0.8)")
            .style("color", "white")
            .style("padding", "8px 12px")
            .style("border-radius", "4px")
            .style("font-size", "12px")
            .style("font-family", "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif")
            .style("pointer-events", "none")
            .style("opacity", 0)
            .style("transition", "opacity 0.3s ease")
            .style("z-index", "1001")
            .style("max-width", "300px")
            .style("word-wrap", "break-word");

        // Add window-level mouse leave handler to ensure tooltips are hidden
        const handleWindowMouseLeave = function() {
            tooltip.interrupt();
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0);
        };
        
        // Add event listener for when mouse leaves the window
        window.addEventListener("blur", handleWindowMouseLeave);
        document.addEventListener("mouseleave", handleWindowMouseLeave);

        // Convert flat data to hierarchical structure
        function buildHierarchy(nodes, links) {
            const nodeMap = new Map();
            const childrenMap = new Map();
            
            // Initialize node map and children map
            nodes.forEach(function(node) {
                nodeMap.set(node.id, {...node, children: []});
                childrenMap.set(node.id, []);
            });
            
            // Build parent-child relationships
            links.forEach(function(link) {
                const parentId = link.source;
                const childId = link.target;
                if (childrenMap.has(parentId)) {
                    childrenMap.get(parentId).push(childId);
                }
            });
            
            // Find root nodes (nodes with no parents)
            const allChildren = new Set();
            links.forEach(function(link) { allChildren.add(link.target); });
            
            const rootNodes = nodes.filter(function(node) { return !allChildren.has(node.id); });
            
            // Build tree structure
            function buildTree(nodeId) {
                const node = nodeMap.get(nodeId);
                if (!node) return null;
                
                const children = childrenMap.get(nodeId) || [];
                node.children = children
                    .map(function(childId) { return buildTree(childId); })
                    .filter(function(child) { return child !== null; });
                
                return node;
            }
            
            // If no clear root, use the first node as root
            if (rootNodes.length === 0 && nodes.length > 0) {
                return buildTree(nodes[0].id);
            }
            
            // If multiple roots, create a virtual root
            if (rootNodes.length > 1) {
                const virtualRoot = {
                    id: "virtual_root",
                    label: "Research Process",
                    children: rootNodes.map(function(node) { return buildTree(node.id); }).filter(function(node) { return node !== null; })
                };
                return virtualRoot;
            }
            
            return buildTree(rootNodes[0].id);
        }

        // Build the tree data
        const treeData = buildHierarchy(graphData.nodes, graphData.links);
        
        // Create tree layout
        const treeLayout = d3.tree()
            .size([config.width - 100, config.height - 100])
            .nodeSize([config.nodeSizeX, config.nodeSizeY]);

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

        // Create force simulation
        const simulation = d3.forceSimulation(root.descendants())
            .force("link", d3.forceLink(root.links())
                .id(d => d.data.id)
                .distance(d => {
                    // Increase distance for expanded nodes
                    const sourceExpanded = expandedNodes.has(d.source.data.id);
                    const targetExpanded = expandedNodes.has(d.target.data.id);
                    const baseDistance = config.nodeSizeY * 1.5; // Increased base distance
                    return baseDistance * (sourceExpanded || targetExpanded ? 3 : 1.5); // Increased multiplier
                })
                .strength(0.7)) // Increased strength to maintain structure
            .force("charge", d3.forceManyBody()
                .strength(d => {
                    // Much stronger repulsion for expanded nodes
                    return expandedNodes.has(d.data.id) ? -2000 : -1000;
                }))
            .force("collide", d3.forceCollide()
                .radius(d => {
                    // Larger collision radius for expanded nodes
                    if (expandedNodes.has(d.data.id)) {
                        const internalNodeCount = d.data.internal_nodes.length;
                        // Increased base radius and multiplier
                        return Math.max(80, internalNodeCount * 15);
                    }
                    return config.nodeRadius * 2; // Increased base collision radius
                })
                .strength(1)) // Maximum collision strength
            .force("x", d3.forceX(d => {
                // Keep nodes near their tree layout x position
                return d.x;
            }).strength(0.5)) // Increased x-positioning force
            .force("y", d3.forceY(d => {
                // Keep nodes near their tree layout y position
                return d.y;
            }).strength(0.5)) // Increased y-positioning force
            .on("tick", ticked);

        function ticked() {
            // Update link positions
            link.attr("d", d3.linkVertical()
                .x(d => d.x)
                .y(d => d.y));

            // Update node positions
            node.attr("transform", d => \`translate(\${d.x}, \${d.y})\`);

            // Update labels
            label.attr("x", d => d.x)
                .attr("y", d => d.y + (d.data.has_internal_nodes && expandedNodes.has(d.data.id) ? 60 : config.nodeRadius + 15));

            // Update expansion indicators
            g.selectAll(".expansion-indicators text")
                .attr("x", d => d.x + config.nodeRadius * 0.8)
                .attr("y", d => d.y - config.nodeRadius * 0.8);

            // Update internal nodes if they exist - container follows parent node
            internalNodeGroups.forEach((internalNodeGroup, parentId) => {
                const parentNode = root.descendants().find(d => d.data.id == parentId);
                if (parentNode && expandedNodes.has(parentId)) {
                    // Update container position to follow parent node
                    internalNodeGroup.attr("transform", \`translate(\${parentNode.x}, \${parentNode.y})\`);
                }
            });
        }

        // Reheat simulation when nodes are expanded/collapsed
        function reheatSimulation() {
            simulation.alpha(0.3).restart();
        }

        // Create links
        const link = g.append("g")
            .attr("stroke", "#999")
            .attr("stroke-opacity", config.edgeOpacity)
            .attr("stroke-width", config.edgeStrokeWidth)
            .attr("fill", "none")
            .selectAll("path")
            .data(root.links())
            .join("path")
            .attr("d", d3.linkVertical()
                .x(function(d) { return d.x; })
                .y(function(d) { return d.y; }))
            .attr("class", "link");

        // Create nodes
        const node = g.append("g")
            .attr("stroke", "#fff")
            .attr("stroke-width", config.nodeStrokeWidth)
            .selectAll("g")
            .data(root.descendants())
            .join("g")
            .attr("class", "node")
            .attr("data-id", function(d) { return d.data.id; })
            .attr("transform", function(d) { return \`translate(\${d.x}, \${d.y})\`; });

        // Add circles for non-expanded nodes and rectangles for expanded nodes
        node.each(function(d) {
            const nodeGroup = d3.select(this);
            
            // Always create circle for main nodes (internal nodes are handled separately)
            nodeGroup.append("circle")
                .attr("r", function() {
                    if (d.data.has_internal_nodes) {
                        return config.nodeRadius * 1.2;
                    }
                    return config.nodeRadius;
                })
                .style("fill", function() {
                    if (d.data.id === "virtual_root") return "#f0f0f0";
                    let color = operationColors[d.data.operation] || operationColors.default;
                    if (color === operationColors.default || d.data.status == "terminated" || d.data.status == "cancelled") {
                        color = statusColors[d.data.status] || statusColors.default;
                    }
                    return color;
                })
                .style("opacity", function() {
                    return d.data.id === "virtual_root" ? 0.3 : config.nodeOpacity;
                })
                .style("stroke", "#fff")
                .style("stroke-width", config.nodeStrokeWidth);
        });

        // Add expansion indicators for nodes with internal nodes
        const expansionIndicator = g.append("g")
            .attr("class", "expansion-indicators")
            .selectAll("text")
            .data(root.descendants().filter(function(d) { return d.data.has_internal_nodes; }))
            .join("text")
            .attr("x", function(d) { return d.x + config.nodeRadius * 0.8; })
            .attr("y", function(d) { return d.y - config.nodeRadius * 0.8; })
            .style("font-size", "16px")
            .style("font-weight", "bold")
            .style("fill", function(d) { return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; })
            .style("pointer-events", "none")
            .style("text-shadow", "1px 1px 2px rgba(255,255,255,0.8)")
            .text(function(d) { return expandedNodes.has(d.data.id) ? "−" : "+"; });

        // Add node labels
        const label = g.append("g")
            .attr("class", "labels")
            .selectAll("text")
            .data(root.descendants())
            .join("text")
            .attr("class", "node-label")
            .attr("x", function(d) { return d.x; })
            .attr("y", function(d) { return d.y + config.nodeRadius + 15; })
            .style("font-size", config.nodeFontSize + "px")
            .style("text-anchor", "middle")
            .style("pointer-events", "none")
            .text(function(d) { return d.data.id === "virtual_root" ? "" : d.data.label; });

        // Node interactions
        node.on("mouseover", function(event, d) {
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle")
                .style("opacity", config.nodeHoverOpacity)
                .style("stroke-width", config.nodeStrokeWidth + 2);
            
            // Clear any existing tooltip animations
            tooltip.interrupt();
            
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0.9);
            
            const tooltipText = d.data.title || d.data.query || "Node " + d.data.id;
            tooltip.html(tooltipText)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 28) + "px");
        })
        .on("mouseout", function(event, d) {
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle")
                .style("opacity", config.nodeOpacity)
                .style("stroke-width", config.nodeStrokeWidth);
            
            // Clear any existing tooltip animations and hide
            tooltip.interrupt();
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0);
        })
        .on("mousemove", function(event, d) {
            // Update tooltip position as mouse moves
            if (d.data.id !== "virtual_root") {
                tooltip.style("left", (event.pageX + 10) + "px")
                       .style("top", (event.pageY - 28) + "px");
            }
        })
        .on("click", function(event, d) {
            // Skip virtual root
            if (d.data.id === "virtual_root") return;
            
            console.log("Node clicked:", d.data.id, "Has internal nodes:", d.data.has_internal_nodes, "Internal nodes:", d.data.internal_nodes);
            
            // Toggle expansion state for nodes with internal nodes
            if (d.data.has_internal_nodes) {
                const isExpanded = expandedNodes.has(d.data.id);
                console.log("Expansion state:", isExpanded);
                
                if (isExpanded) {
                    expandedNodes.delete(d.data.id);
                    hideInternalNodes(d);
                    console.log("Collapsed node:", d.data.id);
                } else {
                    expandedNodes.add(d.data.id);
                    showInternalNodes(d);
                    console.log("Expanded node:", d.data.id);
                }
                
                // Update node shape and size
                updateNodeShape(d);
                
                // Recalculate layout to prevent overlapping with increased delay for smoother transitions
                setTimeout(function() {
                    recalculateLayout();
                }, config.transitionDuration);
            }
            
            showNodeInfo(d.data);
        })
        .call(drag(root));

        // Link interactions
        link.on("mouseover", function() {
            d3.select(this)
                .attr("stroke-opacity", config.edgeHoverOpacity)
                .attr("stroke-width", config.edgeStrokeWidth + 1);
        })
        .on("mouseout", function() {
            d3.select(this)
                .attr("stroke-opacity", config.edgeOpacity)
                .attr("stroke-width", config.edgeStrokeWidth);
        });

        // Drag functions
        function drag(root) {
            function dragstarted(event, d) {
                // Prevent zoom when dragging nodes
                event.sourceEvent.stopPropagation();
                d.fx = d.x;
                d.fy = d.y;
            }

            function dragged(event, d) {
                d.fx = event.x;
                d.fy = event.y;
                
                // Update links
                link.attr("d", d3.linkVertical()
                    .x(function(d) { return d.x; })
                    .y(function(d) { return d.y; }));
                
                // Update nodes (now using transform)
                node.attr("transform", function(d) { return \`translate(\${d.x}, \${d.y})\`; });
                
                // Update labels
                label.attr("x", function(d) { return d.x; })
                    .attr("y", function(d) { return d.y + config.nodeRadius + 15; });
            }

            function dragended(event, d) {
                d.fx = null;
                d.fy = null;
            }

            return d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended);
        }

        // Show node info panel
        function showNodeInfo(node) {
            const infoPanel = document.getElementById("info-panel");
            const infoContent = document.getElementById("info-content");
            
            if (nodeInfoMap[node.id]) {
                infoContent.innerHTML = nodeInfoMap[node.id];
                infoPanel.style.display = "block";
            }
        }

        // Close info panel
        function closeInfoPanel() {
            document.getElementById("info-panel").style.display = "none";
        }

        // Update node shape when expanding/collapsing
        function updateNodeShape(nodeData) {
            // Update expansion indicator
            const expansionIndicator = g.selectAll(".expansion-indicators text")
                .filter(function(d) { return d.data.id === nodeData.data.id; });
            
            expansionIndicator.text(function(d) { 
                return expandedNodes.has(d.data.id) ? "−" : "+"; 
            })
            .style("fill", function(d) { 
                return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; 
            });
            
            // Note: We no longer change the main node shape, as internal nodes are in a separate container
        }

        // Show internal nodes for an expanded parent
        function showInternalNodes(parentNode) {
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
                .attr("transform", \`translate(\${parentX}, \${parentY})\`);
            
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
                .on("mouseover", function() {
                    d3.select(this)
                        .style("fill", "#e9ecef")
                        .style("stroke", "#495057")
                        .style("stroke-width", 3);
                })
                .on("mouseout", function() {
                    d3.select(this)
                        .style("fill", "#f8f9fa")
                        .style("stroke", "#6c757d")
                        .style("stroke-width", 2);
                })
                .on("click", function(event) {
                    event.stopPropagation();
                    // Collapse the expanded node
                    expandedNodes.delete(parentNode.data.id);
                    hideInternalNodes(parentNode);
                    updateNodeShape(parentNode);
                    console.log("Collapsed node via container click:", parentNode.data.id);
                    
                    // Recalculate layout after collapsing
                    setTimeout(function() {
                        recalculateLayout();
                    }, config.transitionDuration / 2);
                });
            
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
                .text(\`Query \${parentNode.data.id}\`);

            // Calculate positions for internal nodes within the container
            const startX = -containerWidth / 2 + padding + nodeSpacing / 2;
            const startY = -containerHeight / 2 + padding + 25 + nodeSpacing / 2; // Account for title
            
            // Create mapping of internal nodes by their IDs with positions inside container
            const internalNodesById = new Map();
            
            // Build hierarchical structure for internal nodes
            function buildInternalHierarchy(internalNodes, edges) {
                const nodeMap = new Map();
                const childrenMap = new Map();
                
                // Initialize node map
                internalNodes.forEach(node => {
                    nodeMap.set(node.id, {...node, children: []});
                    childrenMap.set(node.id, []);
                });
                
                // Build parent-child relationships from edges
                if (edges) {
                    edges.forEach(edge => {
                        const parentId = edge.source;
                        const childId = edge.target;
                        if (childrenMap.has(parentId)) {
                            childrenMap.get(parentId).push(childId);
                        }
                    });
                }
                
                // Find root nodes (nodes with no incoming edges)
                const hasParent = new Set();
                if (edges) {
                    edges.forEach(edge => hasParent.add(edge.target));
                }
                
                const rootNodes = internalNodes.filter(node => !hasParent.has(node.id));
                
                // Build tree structure
                function buildSubtree(nodeId) {
                    const node = nodeMap.get(nodeId);
                    if (!node) return null;
                    
                    const children = childrenMap.get(nodeId) || [];
                    node.children = children
                        .map(childId => buildSubtree(childId))
                        .filter(child => child !== null);
                    
                    return node;
                }
                
                // If no clear hierarchy, arrange in sequence
                if (rootNodes.length === 0 || !edges || edges.length === 0) {
                    return null;
                }
                
                // Build trees from root nodes
                return rootNodes.map(root => buildSubtree(root.id)).filter(tree => tree !== null);
            }
            
            // Try to build hierarchical layout
            const hierarchyTrees = buildInternalHierarchy(parentNode.data.internal_nodes, parentNode.data.internal_edges);
            
            if (hierarchyTrees && hierarchyTrees.length > 0) {
                // Use hierarchical tree layout
                const availableWidth = containerWidth - padding * 2;
                const availableHeight = containerHeight - padding * 2 - 30; // Account for title
                
                // Create a tree layout for each root
                const treeLayout = d3.tree()
                    .size([availableWidth, availableHeight]);
                
                hierarchyTrees.forEach((treeRoot, treeIndex) => {
                    const hierarchy = d3.hierarchy(treeRoot);
                    const treeNodes = treeLayout(hierarchy);
                    
                    // Calculate tree width for positioning
                    const treeWidth = availableWidth / hierarchyTrees.length;
                    const treeStartX = treeIndex * treeWidth;
                    
                    // Position nodes in this tree (relative to container origin)
                    treeNodes.descendants().forEach(node => {
                        const nodeX = treeStartX + (node.x - availableWidth/2) * 0.8; // Scale down a bit
                        const nodeY = node.y * 0.8; // Scale down vertically
                        
                        internalNodesById.set(node.data.id, {
                            ...node.data,
                            x: nodeX,
                            y: nodeY,
                            treeIndex: treeIndex,
                            depth: node.depth
                        });
                    });
                });
            } else {
                // Fallback to grid layout if no clear hierarchy
                parentNode.data.internal_nodes.forEach((node, index) => {
                    const cols = Math.min(4, Math.ceil(Math.sqrt(internalNodeCount)));
                    const rows = Math.ceil(internalNodeCount / cols);
                    const col = index % cols;
                    const row = Math.floor(index / cols);
                    
                    // Position relative to container origin (will be centered later)
                    const nodeX = col * nodeSpacing - (cols - 1) * nodeSpacing / 2;
                    const nodeY = row * nodeSpacing - (rows - 1) * nodeSpacing / 2;
                    
                    internalNodesById.set(node.id, {
                        ...node,
                        x: nodeX,
                        y: nodeY
                    });
                });
            }
            
            // Auto-center all nodes within the container
            const allNodes = Array.from(internalNodesById.values());
            if (allNodes.length > 0) {
                // Calculate bounds of positioned nodes
                const bounds = {
                    minX: Math.min(...allNodes.map(n => n.x)),
                    maxX: Math.max(...allNodes.map(n => n.x)),
                    minY: Math.min(...allNodes.map(n => n.y)),
                    maxY: Math.max(...allNodes.map(n => n.y))
                };
                
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
                allNodes.forEach(node => {
                    node.x += offsetX;
                    node.y += offsetY;
                });
            }

            // Process internal links
            const internalLinks = [];
            if (parentNode.data.internal_edges) {
                console.log("Processing internal edges for node", parentNode.data.id, ":", parentNode.data.internal_edges);
                parentNode.data.internal_edges.forEach(edge => {
                    const sourceNode = internalNodesById.get(edge.source);
                    const targetNode = internalNodesById.get(edge.target);
                    console.log("Edge:", edge.source, "->", edge.target, "Source found:", !!sourceNode, "Target found:", !!targetNode);
                    if (sourceNode && targetNode) {
                        internalLinks.push({
                            source: sourceNode,
                            target: targetNode,
                            sourceId: edge.source,
                            targetId: edge.target
                        });
                    }
                });
                console.log("Created", internalLinks.length, "internal links for node", parentNode.data.id);
            } else {
                console.log("No internal edges found for node", parentNode.data.id);
            }

            // Create links between internal nodes (relative to container)
            const linkGroup = internalNodeGroup.append("g")
                .attr("class", "internal-links");

            const linkPaths = linkGroup.selectAll("path")
                .data(internalLinks)
                .join("path")
                .attr("d", d => {
                    // Use curved links for tree-like appearance when we have hierarchy
                    if (d.source.depth !== undefined && d.target.depth !== undefined) {
                        // Tree-style curved link
                        const sourceX = d.source.x;
                        const sourceY = d.source.y;
                        const targetX = d.target.x;
                        const targetY = d.target.y;
                        const midY = (sourceY + targetY) / 2;
                        return \`M\${sourceX},\${sourceY}C\${sourceX},\${midY} \${targetX},\${midY} \${targetX},\${targetY}\`;
                    } else {
                        // Straight line for grid layout
                        return \`M\${d.source.x},\${d.source.y}L\${d.target.x},\${d.target.y}\`;
                    }
                })
                .style("fill", "none")
                .style("stroke", "#6c757d")
                .style("stroke-width", 1.5)
                .style("stroke-opacity", 0.7)
                .style("marker-end", "url(#arrowhead)")
                .on("mouseover", function() {
                    d3.select(this)
                        .style("stroke-opacity", 1)
                        .style("stroke-width", 2.5)
                        .style("stroke", "#dc3545");
                })
                .on("mouseout", function() {
                    d3.select(this)
                        .style("stroke-opacity", 0.7)
                        .style("stroke-width", 1.5)
                        .style("stroke", "#6c757d");
                });

            // Add internal nodes (relative to container)
            const nodeCircles = internalNodeGroup.selectAll("circle")
                .data(Array.from(internalNodesById.values()))
                .join("circle")
                .attr("r", config.nodeRadius * 0.35)
                .attr("cx", d => d.x)
                .attr("cy", d => d.y)
                .style("fill", d => {
                    let color = operationColors[d.operation] || operationColors.default;
                    if (color === operationColors.default || d.status === "terminated" || d.status === "cancelled") {{
                        color = statusColors[d.status] || statusColors.default;
                    }
                    return color;
                })
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
                .on("mouseover", function(event, d) {
                    // Highlight connected links
                    linkPaths
                        .style("stroke-opacity", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return 1;
                            }
                            return 0.2;
                        })
                        .style("stroke-width", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return 2.5;
                            }
                            return 1.5;
                        })
                        .style("stroke", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return "#dc3545";
                            }
                            return "#6c757d";
                        });

                    d3.select(this)
                        .style("opacity", 1.0)
                        .style("stroke-width", 2.5);
                    
                    // Clear any existing tooltip animations
                    tooltip.interrupt();
                    tooltip.transition()
                        .duration(config.transitionDuration)
                        .style("opacity", 0.9);
                    
                    const tooltipText = d.query || "Internal Node " + d.id;
                    tooltip.html(tooltipText)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 28) + "px");
                })
                .on("mouseout", function(event, d) {
                    // Restore all links
                    linkPaths
                        .style("stroke-opacity", 0.7)
                        .style("stroke-width", 1.5)
                        .style("stroke", "#6c757d");

                    d3.select(this)
                        .style("opacity", 0.9)
                        .style("stroke-width", 1.5);
                    
                    // Clear any existing tooltip animations and hide
                    tooltip.interrupt();
                    tooltip.transition()
                        .duration(config.transitionDuration)
                        .style("opacity", 0);
                })
                .on("mousemove", function(event, d) {
                    // Update tooltip position as mouse moves
                    tooltip.style("left", (event.pageX + 10) + "px")
                           .style("top", (event.pageY - 28) + "px");
                })
                .on("click", function(event, d) {
                    event.stopPropagation();
                    showInternalNodeInfo(d);
                });
        }

        // Hide internal nodes for a collapsed parent
        function hideInternalNodes(parentNode) {
            const internalNodeGroup = internalNodeGroups.get(parentNode.data.id);
            if (internalNodeGroup) {
                internalNodeGroup.remove();
                internalNodeGroups.delete(parentNode.data.id);
            }
            const linkGroup = internalLinkGroups.get(parentNode.data.id);
            if (linkGroup) {
                linkGroup.remove();
                internalLinkGroups.delete(parentNode.data.id);
            }
        }

        // Show info for internal nodes
        function showInternalNodeInfo(internalNode) {
            const infoPanel = document.getElementById("info-panel");
            const infoContent = document.getElementById("info-content");
            
            // Check if we have detailed info for this internal node
            if (nodeInfoMap[internalNode.id]) {
                infoContent.innerHTML = nodeInfoMap[internalNode.id];
            } else {
                // Create simplified info for internal nodes
                const internalInfo = \`
                    <h3>Internal Node \${internalNode.id} Details</h3>
                    <div style="margin-bottom: 15px;">
                        <b>Status:</b> <span style="color: \${statusColors[internalNode.status] || statusColors.default}">\${internalNode.status.toUpperCase()}</span><br>
                        <b>Parent Node:</b> \${internalNode.parentId}<br>
                        <b>Query:</b>
                        <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">\${internalNode.query}</div>
                    </div>
                \`;
                infoContent.innerHTML = internalInfo;
            }
            
            infoPanel.style.display = "block";
        }

        // Make functions globally available
        window.showNodeInfo = showNodeInfo;
        window.closeInfoPanel = closeInfoPanel;
        
        // Zoom control functions
        window.zoomIn = function() {
            svg.transition().duration(300).call(
                zoom.scaleBy, 1.5
            );
        };
        
        window.zoomOut = function() {
            svg.transition().duration(300).call(
                zoom.scaleBy, 1 / 1.5
            );
        };
        
        window.resetZoom = function() {
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
        };

        // Recalculate tree layout to prevent overlapping
        function recalculateLayout() {
            // Update node sizes and forces with stronger values
            simulation.force("collide").radius(d => {
                if (expandedNodes.has(d.data.id)) {
                    const internalNodeCount = d.data.internal_nodes.length;
                    return Math.max(80, internalNodeCount * 15);
                }
                return config.nodeRadius * 2;
            }).strength(1);

            simulation.force("link").distance(d => {
                const sourceExpanded = expandedNodes.has(d.source.data.id);
                const targetExpanded = expandedNodes.has(d.target.data.id);
                const baseDistance = config.nodeSizeY * 1.5;
                return baseDistance * (sourceExpanded || targetExpanded ? 3 : 1.5);
            }).strength(0.7);

            simulation.force("charge").strength(d => {
                return expandedNodes.has(d.data.id) ? -2000 : -1000;
            });

            // Reheat simulation with higher energy
            simulation.alpha(0.5).restart();
        }
        `;

        return d3Script;
    }

    async visualize(outputFile = "research_visualization_d3.html") {
        // Create an interactive D3.js visualization of the research progress
        const logData = await this.loadLog();

        // Validate data structure
        if (!logData) {
            throw new Error("No log data available");
        }
        if (!Array.isArray(logData.nodes)) {
            console.error("logData.nodes is not an array:", logData.nodes);
            throw new Error("logData.nodes must be an array");
        }
        if (!Array.isArray(logData.edges)) {
            console.error("logData.edges is not an array:", logData.edges);
            // Default to empty array if edges is not provided
            logData.edges = [];
        }

        // Create nodes list - exclude internal nodes from main tree
        const nodes = [];
        const idToNode = {};
        for (const node of logData.nodes) {
            idToNode[String(node.id)] = node;
        }

        // Build parent -> [internal nodes] mapping and collect internal edges
        const parentToInternal = {};
        const internalEdges = {}; // Store edges between internal nodes by parent
        for (const node of logData.nodes) {
            const nodeIdStr = String(node.id);
            // Internal node: has a dot and its parent is the part before the first dot
            if (nodeIdStr.includes('.')) {
                const parentId = nodeIdStr.split('.')[0];
                if (!parentToInternal[parentId]) {
                    parentToInternal[parentId] = [];
                }
                parentToInternal[parentId].push(node);
            }
        }

        // Collect edges between internal nodes
        for (const edge of logData.edges) {
            const sourceId = String(edge.from);
            const targetId = String(edge.to);

            // If both nodes are internal nodes and share the same parent
            if (sourceId.includes('.') && targetId.includes('.')) {
                const sourceParent = sourceId.split('.')[0];
                const targetParent = targetId.split('.')[0];
                if (sourceParent === targetParent) {
                    // Store edges with proper structure for D3
                    if (!internalEdges[sourceParent]) {
                        internalEdges[sourceParent] = [];
                    }
                    internalEdges[sourceParent].push({
                        "source": sourceId,  // Changed from "from" to "source"
                        "target": targetId   // Changed from "to" to "target"
                    });
                }
            }
        }

        // Only add main nodes (non-internal) to the tree structure
        for (const node of logData.nodes) {
            const nodeIdStr = String(node.id);
            // Skip internal nodes - they will be shown only when parent is expanded
            if (nodeIdStr.includes('.')) {
                continue;
            }

            const internalNodes = parentToInternal[nodeIdStr] || [];
            // Add edges information to internal nodes
            const nodeInternalEdges = internalEdges[nodeIdStr] || [];

            // First check for operation-based color
            let backgroundColor = this.config.operation_colors[node.operation] || this.config.operation_colors.default;
            // If no operation color found, fall back to status-based coloring
            if (backgroundColor === this.config.operation_colors.default || node.status === "terminated" || node.status === "cancelled") {
                backgroundColor = this.config.status_colors[node.status] || this.config.status_colors.default;
            }

            const nodeData = {
                "id": node.id,
                "label": `Q${node.id}`,
                "title": this._cleanText(node.query),
                "query": this._cleanText(node.query),
                "color": backgroundColor,
                "status": node.status,
                "operation": node.operation || "default",
                "depth": node.depth || 0,
                "breadth": node.breadth || 0,
                "concurrent_group": node.concurrent_group,
                "results": node.results,
                "start_time": node.start_time,
                "duration": node.duration,
                "has_internal_nodes": internalNodes.length > 0,
                "internal_nodes": internalNodes,
                "internal_edges": nodeInternalEdges
            };
            nodes.push(nodeData);
        }

        // Create edges list - only include edges between main nodes
        const edges = [];
        for (const edge of logData.edges) {
            // Skip edges that involve internal nodes
            if (this._isInternalNode(edge.from) || this._isInternalNode(edge.to)) {
                continue;
            }
            edges.push({ "source": edge.from, "target": edge.to });
        }

        // Generate HTML content
        const d3Script = this._generateD3Script(nodes, edges);
        const htmlContent = this.templates.getBaseTemplate().replace('{d3_script}', d3Script);

        // In web context, we'll return the script instead of saving to file
        return {
            htmlContent: htmlContent,
            d3Script: d3Script,
            nodes: nodes,
            edges: edges
        };
    }

    // Method to integrate with existing web app - with state comparison
    async renderToContainer(containerSelector, logData) {
        this.setLogData(logData);
        
        // Compare with previous state to avoid unnecessary re-renders
        if (this.lastLogData && this.isDataEquivalent(this.lastLogData, logData)) {
            console.log('Data unchanged, skipping re-render to prevent shaking');
            return this.lastResult;
        }
        
        this.lastLogData = JSON.parse(JSON.stringify(logData)); // Deep copy for comparison
        
        const result = await this.visualize();
        this.lastResult = result;
        
        // Clear existing content
        const container = document.querySelector(containerSelector);
        if (container) {
            container.innerHTML = '';
            
            // Update config with container dimensions
            const containerRect = container.getBoundingClientRect();
            const vizConfig = {
                width: containerRect.width || 1200,
                height: containerRect.height || 800,
                margin: this.config.margin,
                nodeRadius: this.config.node_radius,
                nodeFontSize: this.config.node_font_size,
                nodeStrokeWidth: this.config.node_stroke_width,
                nodeOpacity: this.config.node_opacity,
                nodeHoverOpacity: this.config.node_hover_opacity,
                edgeStrokeWidth: this.config.edge_stroke_width,
                edgeOpacity: this.config.edge_opacity,
                edgeHoverOpacity: this.config.edge_hover_opacity,
                nodeSizeX: this.config.node_size_x,
                nodeSizeY: this.config.node_size_y,
                animationDuration: this.config.animation_duration,
                transitionDuration: this.config.transition_duration
            };

            // Execute D3 visualization directly without script element
            this._renderD3Visualization(container, result.nodes, result.edges, vizConfig);
        }
        
        return result;
    }

    // Compare two log data objects to determine if they're equivalent
    isDataEquivalent(oldData, newData) {
        if (!oldData || !newData) return false;
        
        // Compare node counts first (quick check)
        if (oldData.nodes?.length !== newData.nodes?.length) return false;
        if (oldData.edges?.length !== newData.edges?.length) return false;
        
        // Compare node IDs and statuses (key changes that matter for visualization)
        const oldNodeMap = new Map();
        const newNodeMap = new Map();
        
        if (oldData.nodes) {
            for (const node of oldData.nodes) {
                oldNodeMap.set(node.id, { status: node.status, hasInternal: !!node.internal_nodes?.length });
            }
        }
        
        if (newData.nodes) {
            for (const node of newData.nodes) {
                newNodeMap.set(node.id, { status: node.status, hasInternal: !!node.internal_nodes?.length });
            }
        }
        
        // Check if any node status or structure has changed
        for (const [id, oldNode] of oldNodeMap) {
            const newNode = newNodeMap.get(id);
            if (!newNode || oldNode.status !== newNode.status || oldNode.hasInternal !== newNode.hasInternal) {
                return false;
            }
        }
        
        // Check for new nodes
        for (const id of newNodeMap.keys()) {
            if (!oldNodeMap.has(id)) {
                return false;
            }
        }
        
        return true; // Data is equivalent
    }

    _renderD3Visualization(container, nodes, edges, config) {
        // Create node info mapping
        const nodeInfoMap = {};
        for (const node of nodes) {
            nodeInfoMap[node.id] = this._createNodeInfoHTML(node);
        }

        // Also add internal nodes to the info mapping
        for (const node of nodes) {
            if (node.internal_nodes) {
                for (const internalNode of node.internal_nodes) {
                    nodeInfoMap[internalNode.id] = this._createNodeInfoHTML(internalNode);
                }
            }
        }

        // Data
        const graphData = {
            nodes: nodes,
            links: edges
        };

        // Color scales
        const statusColors = this.config.status_colors;
        const operationColors = this.config.operation_colors;

        // Expansion state tracking
        const expandedNodes = new Set();
        const internalNodeGroups = new Map();
        const internalLinkGroups = new Map();
        
        // Start with all nodes collapsed by default
        // expandedNodes starts empty - nodes are collapsed by default

        // Setup SVG
        const svg = d3.select(container)
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
            .on("zoom", function(event) {
                g.attr("transform", event.transform);
            });

        svg.call(zoom);

        // Create a group for all elements that will be transformed
        const g = svg.append("g");

        // Create tooltip
        const tooltip = d3.select("body")
            .append("div")
            .attr("class", "tooltip")
            .style("position", "absolute")
            .style("background", "rgba(0, 0, 0, 0.8)")
            .style("color", "white")
            .style("padding", "8px 12px")
            .style("border-radius", "4px")
            .style("font-size", "12px")
            .style("pointer-events", "none")
            .style("opacity", 0)
            .style("transition", "opacity 0.3s ease")
            .style("z-index", "1001");

        // Convert flat data to hierarchical structure
        function buildHierarchy(nodes, links) {
            const nodeMap = new Map();
            const childrenMap = new Map();
            
            // Initialize node map and children map
            nodes.forEach(function(node) {
                nodeMap.set(node.id, {...node, children: []});
                childrenMap.set(node.id, []);
            });
            
            // Build parent-child relationships
            links.forEach(function(link) {
                const parentId = link.source;
                const childId = link.target;
                if (childrenMap.has(parentId)) {
                    childrenMap.get(parentId).push(childId);
                }
            });
            
            // Find root nodes (nodes with no parents)
            const allChildren = new Set();
            links.forEach(function(link) { allChildren.add(link.target); });
            
            const rootNodes = nodes.filter(function(node) { return !allChildren.has(node.id); });
            
            // Build tree structure
            function buildTree(nodeId) {
                const node = nodeMap.get(nodeId);
                if (!node) return null;
                
                const children = childrenMap.get(nodeId) || [];
                node.children = children
                    .map(function(childId) { return buildTree(childId); })
                    .filter(function(child) { return child !== null; });
                
                return node;
            }
            
            // If no clear root, use the first node as root
            if (rootNodes.length === 0 && nodes.length > 0) {
                return buildTree(nodes[0].id);
            }
            
            // If multiple roots, create a virtual root
            if (rootNodes.length > 1) {
                const virtualRoot = {
                    id: "virtual_root",
                    label: "Research Process",
                    children: rootNodes.map(function(node) { return buildTree(node.id); }).filter(function(node) { return node !== null; })
                };
                return virtualRoot;
            }
            
            return buildTree(rootNodes[0].id);
        }

        // Build the tree data
        const treeData = buildHierarchy(graphData.nodes, graphData.links);
        
        // Create tree layout
        const treeLayout = d3.tree()
            .size([config.width - 100, config.height - 100])
            .nodeSize([config.nodeSizeX, config.nodeSizeY]);

        // Create hierarchy and apply initial tree layout
        const root = d3.hierarchy(treeData);
        treeLayout(root);

        // Calculate bounds of all nodes for initial centering
        const allNodes = root.descendants();
        if (allNodes.length === 0) return;
        
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
        const scale = Math.min(scaleX, scaleY, 1);
        
        // Calculate translation to center the tree
        const translateX = config.width / 2 - centerX * scale;
        const translateY = config.height / 2 - centerY * scale;
        
        // Apply initial transform
        const initialTransform = d3.zoomIdentity
            .translate(translateX, translateY)
            .scale(scale);
        
        svg.call(zoom.transform, initialTransform);

        // Create force simulation for dynamic spacing - with stabilization
        const simulation = d3.forceSimulation(root.descendants())
            .force("link", d3.forceLink(root.links())
                .id(d => d.data.id)
                .distance(d => {
                    // Increase distance for expanded nodes
                    const sourceExpanded = expandedNodes.has(d.source.data.id);
                    const targetExpanded = expandedNodes.has(d.target.data.id);
                    const baseDistance = config.nodeSizeY * 1.2; // Reduced from 1.5
                    return baseDistance * (sourceExpanded || targetExpanded ? 2 : 1.2); // Reduced multiplier
                })
                .strength(0.3)) // Reduced strength for gentler movement
            .force("charge", d3.forceManyBody()
                .strength(d => {
                    // Gentler repulsion to reduce oscillation
                    return expandedNodes.has(d.data.id) ? -800 : -400; // Reduced values
                }))
            .force("collide", d3.forceCollide()
                .radius(d => {
                    // Larger collision radius for expanded nodes
                    if (expandedNodes.has(d.data.id)) {
                        const internalNodeCount = d.data.internal_nodes ? d.data.internal_nodes.length : 0;
                        return Math.max(60, internalNodeCount * 10); // Reduced values
                    }
                    return config.nodeRadius * 1.8; // Reduced from 2
                })
                .strength(0.8)) // Reduced collision strength
            .force("x", d3.forceX(d => {
                // Keep nodes near their tree layout x position
                return d.x;
            }).strength(0.3)) // Reduced positioning force
            .force("y", d3.forceY(d => {
                // Keep nodes near their tree layout y position
                return d.y;
            }).strength(0.3)) // Reduced positioning force
            .alphaDecay(0.05) // Slower decay for more stable convergence
            .velocityDecay(0.7) // Higher velocity decay to reduce oscillation
            .on("tick", ticked);

        // Track if simulation has stabilized
        let isStabilized = false;
        let lastUpdateTime = 0;
        const stabilizationThreshold = 0.01; // Minimum alpha for stabilization

        function ticked() {
            const now = performance.now();
            
            // Only update visuals if enough time has passed or if not stabilized
            if (now - lastUpdateTime < 16 || (isStabilized && simulation.alpha() < stabilizationThreshold)) {
                return; // Skip update to reduce frequent redraws
            }
            
            lastUpdateTime = now;
            
            // Check if simulation has stabilized
            if (simulation.alpha() < stabilizationThreshold && !isStabilized) {
                isStabilized = true;
                console.log('Simulation stabilized');
                // Fix node positions when stabilized to prevent further movement
                root.descendants().forEach(d => {
                    if (Math.abs(d.vx) < 0.1 && Math.abs(d.vy) < 0.1) {
                        d.fx = d.x;
                        d.fy = d.y;
                    }
                });
            }

            // Update link positions
            link.attr("d", d3.linkVertical()
                .x(d => d.x)
                .y(d => d.y));

            // Update node positions
            node.attr("transform", d => `translate(${d.x}, ${d.y})`);

            // Update labels
            label.attr("x", d => d.x)
                .attr("y", d => d.y + (d.data.has_internal_nodes && expandedNodes.has(d.data.id) ? 60 : config.nodeRadius + 15));

            // Update expansion indicators
            g.selectAll(".expansion-indicators text")
                .attr("x", d => d.x + config.nodeRadius * 0.8)
                .attr("y", d => d.y - config.nodeRadius * 0.8);

            // Update internal nodes if they exist - container follows parent node
            internalNodeGroups.forEach((internalNodeGroup, parentId) => {
                const parentNode = root.descendants().find(d => d.data.id == parentId);
                if (parentNode && expandedNodes.has(parentId)) {
                    // Update container position to follow parent node
                    internalNodeGroup.attr("transform", `translate(${parentNode.x}, ${parentNode.y})`);
                }
            });
        }

        // Gentle simulation restart when nodes are expanded/collapsed
        function reheatSimulation() {
            // Unfix nodes that were previously stabilized
            root.descendants().forEach(d => {
                if (d.fx !== null || d.fy !== null) {
                    d.fx = null;
                    d.fy = null;
                }
            });
            
            isStabilized = false;
            simulation.alpha(0.1).restart(); // Gentler restart
        }

        // Recalculate tree layout to prevent overlapping
        function recalculateLayout() {
            // Update node sizes and forces with gentler values
            simulation.force("collide").radius(d => {
                if (expandedNodes.has(d.data.id)) {
                    const internalNodeCount = d.data.internal_nodes ? d.data.internal_nodes.length : 0;
                    return Math.max(60, internalNodeCount * 10); // Reduced values
                }
                return config.nodeRadius * 1.8;
            }).strength(0.8);

            simulation.force("link").distance(d => {
                const sourceExpanded = expandedNodes.has(d.source.data.id);
                const targetExpanded = expandedNodes.has(d.target.data.id);
                const baseDistance = config.nodeSizeY * 1.2;
                return baseDistance * (sourceExpanded || targetExpanded ? 2 : 1.2);
            }).strength(0.3);

            simulation.force("charge").strength(d => {
                return expandedNodes.has(d.data.id) ? -800 : -400; // Reduced values
            });

            // Gentle reheat with lower energy
            reheatSimulation();
        }

        // Drag functions
        function drag(simulation) {
            function dragstarted(event, d) {
                // Prevent zoom when dragging nodes
                event.sourceEvent.stopPropagation();
                if (!event.active) simulation.alphaTarget(0.3).restart();
                d.fx = d.x;
                d.fy = d.y;
            }

            function dragged(event, d) {
                d.fx = event.x;
                d.fy = event.y;
            }

            function dragended(event, d) {
                if (!event.active) simulation.alphaTarget(0);
                d.fx = null;
                d.fy = null;
            }

            return d3.drag()
                .on("start", dragstarted)
                .on("drag", dragged)
                .on("end", dragended);
        }

        // Since nodes start collapsed, no need to show internal nodes on initial load
        // Layout is already optimized for collapsed state

        // Create links
        const link = g.append("g")
            .attr("stroke", "#999")
            .attr("stroke-opacity", config.edgeOpacity)
            .attr("stroke-width", config.edgeStrokeWidth)
            .attr("fill", "none")
            .selectAll("path")
            .data(root.links())
            .join("path")
            .attr("d", d3.linkVertical()
                .x(function(d) { return d.x; })
                .y(function(d) { return d.y; }))
            .attr("class", "link");

        // Create nodes
        const node = g.append("g")
            .attr("stroke", "#fff")
            .attr("stroke-width", config.nodeStrokeWidth)
            .selectAll("g")
            .data(root.descendants())
            .join("g")
            .attr("class", "node")
            .attr("data-id", function(d) { return d.data.id; })
            .attr("transform", function(d) { return `translate(${d.x}, ${d.y})`; });

        // Add circles for nodes
        node.each(function(d) {
            const nodeGroup = d3.select(this);
            
            nodeGroup.append("circle")
                .attr("r", function() {
                    if (d.data.has_internal_nodes) {
                        return config.nodeRadius * 1.2;
                    }
                    return config.nodeRadius;
                })
                .style("fill", function() {
                    if (d.data.id === "virtual_root") return "#f0f0f0";
                    let color = operationColors[d.data.operation] || operationColors.default;
                    if (color === operationColors.default || d.data.status == "terminated" || d.data.status == "cancelled") {
                        color = statusColors[d.data.status] || statusColors.default;
                    }
                    return color;
                })
                .style("opacity", function() {
                    return d.data.id === "virtual_root" ? 0.3 : config.nodeOpacity;
                })
                .style("stroke", "#fff")
                .style("stroke-width", config.nodeStrokeWidth);
        });

        // Add expansion indicators for nodes with internal nodes
        const expansionIndicator = g.append("g")
            .attr("class", "expansion-indicators")
            .selectAll("text")
            .data(root.descendants().filter(function(d) { return d.data.has_internal_nodes; }))
            .join("text")
            .attr("x", function(d) { return d.x + config.nodeRadius * 0.8; })
            .attr("y", function(d) { return d.y - config.nodeRadius * 0.8; })
            .style("font-size", "16px")
            .style("font-weight", "bold")
            .style("fill", function(d) { return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; })
            .style("pointer-events", "none")
            .style("text-shadow", "1px 1px 2px rgba(255,255,255,0.8)")
            .text(function(d) { return expandedNodes.has(d.data.id) ? "−" : "+"; });

        // Add node labels
        const label = g.append("g")
            .attr("class", "labels")
            .selectAll("text")
            .data(root.descendants())
            .join("text")
            .attr("class", "node-label")
            .attr("x", function(d) { return d.x; })
            .attr("y", function(d) { return d.y + config.nodeRadius + 15; })
            .style("font-size", config.nodeFontSize + "px")
            .style("text-anchor", "middle")
            .style("pointer-events", "none")
            .text(function(d) { return d.data.id === "virtual_root" ? "" : d.data.label; });

        // Node interactions
        node.on("mouseover", function(event, d) {
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle")
                .style("opacity", config.nodeHoverOpacity)
                .style("stroke-width", config.nodeStrokeWidth + 2);
            
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0.9);
            tooltip.html(d.data.title || d.data.query || "Node " + d.data.id)
                .style("left", (event.pageX + 10) + "px")
                .style("top", (event.pageY - 28) + "px");
        })
        .on("mouseout", function(event, d) {
            if (d.data.id === "virtual_root") return;
            
            d3.select(this).select("circle")
                .style("opacity", config.nodeOpacity)
                .style("stroke-width", config.nodeStrokeWidth);
            
            tooltip.transition()
                .duration(config.transitionDuration)
                .style("opacity", 0);
        })
        .on("click", function(event, d) {
            if (d.data.id === "virtual_root") return;
            
            console.log("Node clicked:", d.data.id, "Has internal nodes:", d.data.has_internal_nodes, "Internal nodes:", d.data.internal_nodes);
            
            // Toggle expansion state for nodes with internal nodes
            if (d.data.has_internal_nodes) {
                const isExpanded = expandedNodes.has(d.data.id);
                console.log("Expansion state:", isExpanded);
                
                if (isExpanded) {
                    expandedNodes.delete(d.data.id);
                    hideInternalNodes(d);
                    console.log("Collapsed node:", d.data.id);
                } else {
                    expandedNodes.add(d.data.id);
                    showInternalNodes(d);
                    console.log("Expanded node:", d.data.id);
                }
                
                // Update expansion indicator
                updateNodeShape(d);
                
                // Recalculate layout to prevent overlapping with increased delay for smoother transitions
                setTimeout(function() {
                    recalculateLayout();
                }, config.transitionDuration);
            }
            
            showNodeInfo(d.data);
        })
        .call(drag(simulation));

        // Update node shape when expanding/collapsing
        function updateNodeShape(nodeData) {
            // Update expansion indicator
            const expansionIndicator = g.selectAll(".expansion-indicators text")
                .filter(function(d) { return d.data.id === nodeData.data.id; });
            
            expansionIndicator.text(function(d) { 
                return expandedNodes.has(d.data.id) ? "−" : "+"; 
            })
            .style("fill", function(d) { 
                return expandedNodes.has(d.data.id) ? "#FF4444" : "#333"; 
            });
        }

        // Show internal nodes for an expanded parent
        function showInternalNodes(parentNode) {
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
                .attr("transform", `translate(${parentX}, ${parentY})`);
            
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
                .on("mouseover", function() {
                    d3.select(this)
                        .style("fill", "#e9ecef")
                        .style("stroke", "#495057")
                        .style("stroke-width", 3);
                })
                .on("mouseout", function() {
                    d3.select(this)
                        .style("fill", "#f8f9fa")
                        .style("stroke", "#6c757d")
                        .style("stroke-width", 2);
                })
                .on("click", function(event) {
                    event.stopPropagation();
                    // Collapse the expanded node
                    expandedNodes.delete(parentNode.data.id);
                    hideInternalNodes(parentNode);
                    updateNodeShape(parentNode);
                    console.log("Collapsed node via container click:", parentNode.data.id);
                });
            
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
                .text(`Query ${parentNode.data.id}`);

            // Create mapping of internal nodes by their IDs with positions inside container
            const internalNodesById = new Map();
            
            // Build hierarchical structure for internal nodes
            function buildInternalHierarchy(internalNodes, edges) {
                const nodeMap = new Map();
                const childrenMap = new Map();
                
                // Initialize node map
                internalNodes.forEach(node => {
                    nodeMap.set(node.id, {...node, children: []});
                    childrenMap.set(node.id, []);
                });
                
                // Build parent-child relationships from edges
                if (edges) {
                    edges.forEach(edge => {
                        const parentId = edge.source;
                        const childId = edge.target;
                        if (childrenMap.has(parentId)) {
                            childrenMap.get(parentId).push(childId);
                        }
                    });
                }
                
                // Find root nodes (nodes with no incoming edges)
                const hasParent = new Set();
                if (edges) {
                    edges.forEach(edge => hasParent.add(edge.target));
                }
                
                const rootNodes = internalNodes.filter(node => !hasParent.has(node.id));
                
                // Build tree structure
                function buildSubtree(nodeId) {
                    const node = nodeMap.get(nodeId);
                    if (!node) return null;
                    
                    const children = childrenMap.get(nodeId) || [];
                    node.children = children
                        .map(childId => buildSubtree(childId))
                        .filter(child => child !== null);
                    
                    return node;
                }
                
                // If no clear hierarchy, arrange in sequence
                if (rootNodes.length === 0 || !edges || edges.length === 0) {
                    return null;
                }
                
                // Build trees from root nodes
                return rootNodes.map(root => buildSubtree(root.id)).filter(tree => tree !== null);
            }
            
            // Try to build hierarchical layout
            const hierarchyTrees = buildInternalHierarchy(parentNode.data.internal_nodes, parentNode.data.internal_edges);
            
            if (hierarchyTrees && hierarchyTrees.length > 0) {
                // Use hierarchical tree layout
                const availableWidth = containerWidth - padding * 2;
                const availableHeight = containerHeight - padding * 2 - 30; // Account for title
                
                // Create a tree layout for each root
                const treeLayout = d3.tree()
                    .size([availableWidth, availableHeight]);
                
                hierarchyTrees.forEach((treeRoot, treeIndex) => {
                    const hierarchy = d3.hierarchy(treeRoot);
                    const treeNodes = treeLayout(hierarchy);
                    
                    // Calculate tree width for positioning
                    const treeWidth = availableWidth / hierarchyTrees.length;
                    const treeStartX = treeIndex * treeWidth;
                    
                    // Position nodes in this tree (relative to container origin)
                    treeNodes.descendants().forEach(node => {
                        const nodeX = treeStartX + (node.x - availableWidth/2) * 0.8; // Scale down a bit
                        const nodeY = node.y * 0.8; // Scale down vertically
                        
                        internalNodesById.set(node.data.id, {
                            ...node.data,
                            x: nodeX,
                            y: nodeY,
                            treeIndex: treeIndex,
                            depth: node.depth
                        });
                    });
                });
            } else {
                // Fallback to grid layout if no clear hierarchy
                parentNode.data.internal_nodes.forEach((node, index) => {
                    const cols = Math.min(4, Math.ceil(Math.sqrt(internalNodeCount)));
                    const rows = Math.ceil(internalNodeCount / cols);
                    const col = index % cols;
                    const row = Math.floor(index / cols);
                    
                    // Position relative to container origin (will be centered later)
                    const nodeX = col * nodeSpacing - (cols - 1) * nodeSpacing / 2;
                    const nodeY = row * nodeSpacing - (rows - 1) * nodeSpacing / 2;
                    
                    internalNodesById.set(node.id, {
                        ...node,
                        x: nodeX,
                        y: nodeY
                    });
                });
            }
            
            // Auto-center all nodes within the container
            const allNodes = Array.from(internalNodesById.values());
            if (allNodes.length > 0) {
                // Calculate bounds of positioned nodes
                const bounds = {
                    minX: Math.min(...allNodes.map(n => n.x)),
                    maxX: Math.max(...allNodes.map(n => n.x)),
                    minY: Math.min(...allNodes.map(n => n.y)),
                    maxY: Math.max(...allNodes.map(n => n.y))
                };
                
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
                allNodes.forEach(node => {
                    node.x += offsetX;
                    node.y += offsetY;
                });
            }

            // Process internal links
            const internalLinks = [];
            if (parentNode.data.internal_edges) {
                console.log("Processing internal edges for node", parentNode.data.id, ":", parentNode.data.internal_edges);
                parentNode.data.internal_edges.forEach(edge => {
                    const sourceNode = internalNodesById.get(edge.source);
                    const targetNode = internalNodesById.get(edge.target);
                    console.log("Edge:", edge.source, "->", edge.target, "Source found:", !!sourceNode, "Target found:", !!targetNode);
                    if (sourceNode && targetNode) {
                        internalLinks.push({
                            source: sourceNode,
                            target: targetNode,
                            sourceId: edge.source,
                            targetId: edge.target
                        });
                    }
                });
                console.log("Created", internalLinks.length, "internal links for node", parentNode.data.id);
            } else {
                console.log("No internal edges found for node", parentNode.data.id);
            }

            // Create links between internal nodes (relative to container)
            const linkGroup = internalNodeGroup.append("g")
                .attr("class", "internal-links");

            const linkPaths = linkGroup.selectAll("path")
                .data(internalLinks)
                .join("path")
                .attr("d", d => {
                    // Use curved links for tree-like appearance when we have hierarchy
                    if (d.source.depth !== undefined && d.target.depth !== undefined) {
                        // Tree-style curved link
                        const sourceX = d.source.x;
                        const sourceY = d.source.y;
                        const targetX = d.target.x;
                        const targetY = d.target.y;
                        const midY = (sourceY + targetY) / 2;
                        return `M${sourceX},${sourceY}C${sourceX},${midY} ${targetX},${midY} ${targetX},${targetY}`;
                    } else {
                        // Straight line for grid layout
                        return `M${d.source.x},${d.source.y}L${d.target.x},${d.target.y}`;
                    }
                })
                .style("fill", "none")
                .style("stroke", "#6c757d")
                .style("stroke-width", 1.5)
                .style("stroke-opacity", 0.7)
                .style("marker-end", "url(#arrowhead)")
                .on("mouseover", function() {
                    d3.select(this)
                        .style("stroke-opacity", 1)
                        .style("stroke-width", 2.5)
                        .style("stroke", "#dc3545");
                })
                .on("mouseout", function() {
                    d3.select(this)
                        .style("stroke-opacity", 0.7)
                        .style("stroke-width", 1.5)
                        .style("stroke", "#6c757d");
                });

            // Add internal nodes (relative to container)
            const nodeCircles = internalNodeGroup.selectAll("circle")
                .data(Array.from(internalNodesById.values()))
                .join("circle")
                .attr("r", config.nodeRadius * 0.35)
                .attr("cx", d => d.x)
                .attr("cy", d => d.y)
                .style("fill", d => {
                    let color = operationColors[d.operation] || operationColors.default;
                    if (color === operationColors.default || d.status === "terminated" || d.status === "cancelled") {
                        color = statusColors[d.status] || statusColors.default;
                    }
                    return color;
                })
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
                .on("mouseover", function(event, d) {
                    // Highlight connected links
                    linkPaths
                        .style("stroke-opacity", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return 1;
                            }
                            return 0.2;
                        })
                        .style("stroke-width", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return 2.5;
                            }
                            return 1.5;
                        })
                        .style("stroke", link => {
                            if (link.sourceId === d.id || link.targetId === d.id) {
                                return "#dc3545";
                            }
                            return "#6c757d";
                        });

                    d3.select(this)
                        .style("opacity", 1.0)
                        .style("stroke-width", 2.5);
                    
                    tooltip.transition()
                        .duration(config.transitionDuration)
                        .style("opacity", 0.9);
                    tooltip.html(d.query || "Internal Node " + d.id)
                        .style("left", (event.pageX + 10) + "px")
                        .style("top", (event.pageY - 28) + "px");
                })
                .on("mouseout", function(event, d) {
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
                })
                .on("click", function(event, d) {
                    event.stopPropagation();
                    showInternalNodeInfo(d);
                });
        }

        // Hide internal nodes for a collapsed parent
        function hideInternalNodes(parentNode) {
            const internalNodeGroup = internalNodeGroups.get(parentNode.data.id);
            if (internalNodeGroup) {
                internalNodeGroup.remove();
                internalNodeGroups.delete(parentNode.data.id);
            }
            const linkGroup = internalLinkGroups.get(parentNode.data.id);
            if (linkGroup) {
                linkGroup.remove();
                internalLinkGroups.delete(parentNode.data.id);
            }
        }

        // Show info for internal nodes
        function showInternalNodeInfo(internalNode) {
            const infoPanel = document.getElementById("infoPanel");
            const infoContent = document.getElementById("infoPanelContent");
            
            // Check if we have detailed info for this internal node
            if (nodeInfoMap[internalNode.id]) {
                if (infoPanel && infoContent) {
                    infoContent.innerHTML = nodeInfoMap[internalNode.id];
                    infoPanel.style.display = "block";
                }
            } else {
                // Create simplified info for internal nodes
                const internalInfo = `
                    <h3>Internal Node ${internalNode.id} Details</h3>
                    <div style="margin-bottom: 15px;">
                        <b>Status:</b> <span style="color: ${statusColors[internalNode.status] || statusColors.default}">${internalNode.status.toUpperCase()}</span><br>
                        <b>Parent Node:</b> ${internalNode.parentId || 'Unknown'}<br>
                        <b>Query:</b>
                        <div style="padding: 8px; background: #f5f5f5; border-radius: 4px; margin: 5px 0;">${internalNode.query}</div>
                    </div>
                `;
                if (infoPanel && infoContent) {
                    infoContent.innerHTML = internalInfo;
                    infoPanel.style.display = "block";
                }
            }
        }

        // Show node info panel
        function showNodeInfo(node) {
            const infoPanel = document.getElementById("infoPanel");
            const infoContent = document.getElementById("infoPanelContent");
            
            if (infoPanel && infoContent && nodeInfoMap[node.id]) {
                infoContent.innerHTML = nodeInfoMap[node.id];
                infoPanel.style.display = "block";
            }
        }

        // Make zoom functions globally available for controls
        window.zoomIn = function() {
            svg.transition().duration(300).call(
                zoom.scaleBy, 1.5
            );
        };
        
        window.zoomOut = function() {
            svg.transition().duration(300).call(
                zoom.scaleBy, 1 / 1.5
            );
        };
        
        window.resetZoom = function() {
            svg.transition().duration(300).call(
                zoom.transform,
                initialTransform
            );
        };

        window.closeInfoPanel = function() {
            const infoPanel = document.getElementById("infoPanel");
            if (infoPanel) {
                infoPanel.style.display = "none";
            }
        };

        // Expand all nodes with internal nodes
        window.expandAll = function() {
            root.descendants().forEach(d => {
                if (d.data.has_internal_nodes && !expandedNodes.has(d.data.id)) {
                    expandedNodes.add(d.data.id);
                    showInternalNodes(d);
                    updateNodeShape(d);
                }
            });
            // Recalculate layout after expanding all
            setTimeout(() => {
                recalculateLayout();
            }, config.transitionDuration);
        };

        // Collapse all expanded nodes
        window.collapseAll = function() {
            const nodesToCollapse = Array.from(expandedNodes);
            nodesToCollapse.forEach(nodeId => {
                const nodeData = root.descendants().find(d => d.data.id == nodeId);
                if (nodeData) {
                    expandedNodes.delete(nodeId);
                    hideInternalNodes(nodeData);
                    updateNodeShape(nodeData);
                }
            });
            // Recalculate layout after collapsing all
            setTimeout(() => {
                recalculateLayout();
            }, config.transitionDuration);
        };
    }
}

// Export for use in other modules
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { ResearchVisualizer, VisualizationConfigD3, BaseResearchVisualizer };
} else {
    // Browser environment
    window.ResearchVisualizer = ResearchVisualizer;
    window.VisualizationConfigD3 = VisualizationConfigD3;
    window.BaseResearchVisualizer = BaseResearchVisualizer;
}
