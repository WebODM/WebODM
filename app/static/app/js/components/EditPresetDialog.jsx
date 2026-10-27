import '../css/EditPresetDialog.scss';
import React from 'react';
import FormDialog from './FormDialog';
import ProcessingNodeOption from './ProcessingNodeOption';
import PresetUtils from '../classes/PresetUtils';
import TaskOptionsPluginItems from './TaskOptionsPluginItems';
import PropTypes from 'prop-types';
import values from 'object.values';
import { _ } from '../classes/gettext';

if (!Object.values) {
    values.shim();
}

// Do not apply to WebODM, can cause confusion
const OPTS_BLACKLIST = ['build-overviews', 'orthophoto-no-tiled', 'orthophoto-compression', 'orthophoto-png', 'orthophoto-kmz', 'pc-copc', 'pc-las', 'pc-ply', 'pc-csv', 'pc-ept', 'cog', 'gltf'];

// Option groups
const OPTS_GROUPS = [
    {
        id: 'input',
        name: _('Input & Preprocessing'),
        icon: 'fa fa-image',
        subgroups: [
            { id: 'camera', name: _('Camera Configuration') },
            { id: 'masks', name: _('Masking') },
            { id: 'multispectral', name: _('Multispectral') },
            { id: 'video', name: _('Video Input') }
        ]
    },
    {
        id: 'boundscrop',
        name: _('Bounds & Cropping'),
        icon: 'fa fa-crop',
        subgroups: [
            { id: 'bounds', name: _('Boundary') }
        ]
    },
    {
        id: 'crs',
        name: _('Coordinate Reference System'),
        icon: 'fa fa-globe',
        subgroups: [
            { id: 'crs-opts', name: _('Options') },
        ]
    },
    {
        id: 'sfm',
        name: _('Structure From Motion'),
        icon: 'fa fa-camera',
        subgroups: [
            { id: 'feature-extraction', name: _('Feature Extraction') },
            { id: 'feature-matching', name: _('Feature Matching') },
            { id: 'sparse-reconstruction', name: _('Reconstruction') },
            { id: 'gps', name: _('Georeferencing') }
        ]
    },
    {
        id: 'mvs',
        name: _('Point Cloud'),
        icon: 'fa fa-pointcloud',
        subgroups: [
            { id: 'generation', name: _('Generation') },
            { id: 'filtering', name: _('Filtering') },
            { id: 'postprocess', name: _('Post-Processing') }
        ]
    },
    {
        id: 'mesh',
        name: _('Meshing'),
        icon: 'fa fa-cube',
        subgroups: [
            { id: 'mesh-gen', name: _('Mesh Generation') }
        ]
    },
    {
        id: 'texturing',
        name: _('Texturing'),
        icon: 'fab fa-connectdevelop',
        subgroups: [
            { id: 'texture-opts', name: _('Texture Options') }
        ]
    },
    {
        id: 'dem',
        name: _('Digital Elevation Models'),
        icon: 'fa fa-chart-area',
        subgroups: [
            { id: 'dem-outputs', name: _('Outputs') },
            { id: 'dem-generation', name: _('Resolution & Sampling') },
            { id: 'smrf', name: _('Ground Classification (SMRF)') }
        ]
    },
    {
        id: 'orthophoto',
        name: _('Orthophoto'),
        icon: 'fa fa-map',
        subgroups: [
            { id: 'ortho-opts', name: _('Orthophoto Options') }
        ]
    },
    {
        id: 'tiles',
        name: _('Tiles'),
        icon: 'fas fa-th',
        subgroups: [
            { id: 'tiles-opts', name: _('Tiles Options') }
        ]
    },
    {
        id: 'system',
        name: _('System & Pipeline Control'),
        icon: 'fa fa-cogs',
        subgroups: [
            { id: 'performance', name: _('Performance') },
            { id: 'pipeline', name: _('Pipeline Control') }
        ]
    },
    {
        id: 'split-merge',
        name: _('Split/Merge'),
        icon: 'fa fa-sitemap',
        subgroups: [
            { id: 'splitting', name: _('Splitting') },
            { id: 'merging', name: _('Merging') }
        ]
    },
];

// Map each option to its group and subgroup
const OPTION_GROUP_MAP = {
    // Input & Preprocessing
    'camera-lens': { group: 'input', subgroup: 'camera' },
    'cameras': { group: 'input', subgroup: 'camera' },
    'use-fixed-camera-params': { group: 'input', subgroup: 'camera' },
    'rolling-shutter': { group: 'input', subgroup: 'camera' },
    'rolling-shutter-readout': { group: 'input', subgroup: 'camera' },
    'rolling-shutter-correction': { group: 'input', subgroup: 'camera' },
    'ignore-gsd': { group: 'input', subgroup: 'camera' },
    
    'bg-removal': { group: 'input', subgroup: 'masks' },
    'sky-removal': { group: 'input', subgroup: 'masks' },

    'primary-band': { group: 'input', subgroup: 'multispectral' },
    'radiometric-calibration': { group: 'input', subgroup: 'multispectral' },
    'skip-band-alignment': { group: 'input', subgroup: 'multispectral' },
    'thermal-distance': { group: 'input', subgroup: 'multispectral' },
    'thermal-humidity': { group: 'input', subgroup: 'multispectral' },
    'thermal-emissivity': { group: 'input', subgroup: 'multispectral' },
    'thermal-ambient-temperature': { group: 'input', subgroup: 'multispectral' },
    'thermal-reflected-temperature': { group: 'input', subgroup: 'multispectral' },
    
    'video-limit': { group: 'input', subgroup: 'video' },
    'video-resolution': { group: 'input', subgroup: 'video' },
    
    // CRS
    'crs': { group: 'crs', subgroup: 'crs-opts' },
    'report-units': { group: 'crs', subgroup: 'crs-opts' },
    
    // Split/Merge
    'split': { group: 'split-merge', subgroup: 'splitting' },
    'split-overlap': { group: 'split-merge', subgroup: 'splitting' },
    'sm-cluster': { group: 'split-merge', subgroup: 'splitting' },
    
    'merge': { group: 'split-merge', subgroup: 'merging' },
    'merge-skip-blending': { group: 'split-merge', subgroup: 'merging' },
    'sm-no-align': { group: 'split-merge', subgroup: 'merging' },
    
    // Structure from Motion
    'feature-type': { group: 'sfm', subgroup: 'feature-extraction' },
    'feature-quality': { group: 'sfm', subgroup: 'feature-extraction' },
    'min-num-features': { group: 'sfm', subgroup: 'feature-extraction' },
    
    'matcher-type': { group: 'sfm', subgroup: 'feature-matching' },
    'matcher-neighbors': { group: 'sfm', subgroup: 'feature-matching' },
    'matcher-order': { group: 'sfm', subgroup: 'feature-matching' },
    
    'sfm-algorithm': { group: 'sfm', subgroup: 'sparse-reconstruction' },
    'sfm-no-partial': { group: 'sfm', subgroup: 'sparse-reconstruction' },
    'use-hybrid-bundle-adjustment': { group: 'sfm', subgroup: 'sparse-reconstruction' },
    'min-track-length': { group: 'sfm', subgroup: 'sparse-reconstruction' },
    
    'force-gps': { group: 'sfm', subgroup: 'gps' },
    'gps-accuracy': { group: 'sfm', subgroup: 'gps' },
    'gps-z-offset': { group: 'sfm', subgroup: 'gps' },
    'use-exif': { group: 'sfm', subgroup: 'gps' },
    
    // Dense
    'pc-quality': { group: 'mvs', subgroup: 'generation' },
    'pc-tile': { group: 'mvs', subgroup: 'generation' },
    
    'depthmap-min-consistent-views': { group: 'mvs', subgroup: 'generation' },
    
    // MVS
    'pc-filter': { group: 'mvs', subgroup: 'filtering' },
    'pc-skip-geometric': { group: 'mvs', subgroup: 'filtering' },
    'pc-textureless': { group: 'mvs', subgroup: 'filtering' },
    'pc-sample': { group: 'mvs', subgroup: 'filtering' },
    
    'pc-classify': { group: 'mvs', subgroup: 'postprocess' },
    'pc-rectify': { group: 'mvs', subgroup: 'postprocess' },
    
    // Meshing
    'skip-3dmodel': { group: 'mesh', subgroup: 'mesh-gen' },
    'mesh-octree-depth': { group: 'mesh', subgroup: 'mesh-gen' },
    'mesh-size': { group: 'mesh', subgroup: 'mesh-gen' },
    
    // Texturing - Texture Options
    'texturing-single-material': { group: 'texturing', subgroup: 'texture-opts' },
    'texturing-keep-unseen-faces': { group: 'texturing', subgroup: 'texture-opts' },
    'texturing-skip-global-seam-leveling': { group: 'texturing', subgroup: 'texture-opts' },
    'texturing-data-term': { group: 'texturing', subgroup: 'texture-opts' },
    'texturing-regularization': { group: 'texturing', subgroup: 'texture-opts' },
    
    // Bounds/cropping
    'auto-boundary': { group: 'boundscrop', subgroup: 'bounds' },
    'auto-boundary-distance': { group: 'boundscrop', subgroup: 'bounds' },
    'boundary': { group: 'boundscrop', subgroup: 'bounds' },
    'crop': { group: 'boundscrop', subgroup: 'bounds' },
    
    // Digital Elevation Models
    'dsm': { group: 'dem', subgroup: 'dem-outputs' },
    'dtm': { group: 'dem', subgroup: 'dem-outputs' },
    'dem-euclidean-map': { group: 'dem', subgroup: 'dem-outputs' },
    
    'dem-resolution': { group: 'dem', subgroup: 'dem-generation' },
    'dem-decimation': { group: 'dem', subgroup: 'dem-generation' },
    'dem-gapfill-steps': { group: 'dem', subgroup: 'dem-generation' },
    
    'smrf-scalar': { group: 'dem', subgroup: 'smrf' },
    'smrf-slope': { group: 'dem', subgroup: 'smrf' },
    'smrf-threshold': { group: 'dem', subgroup: 'smrf' },
    'smrf-window': { group: 'dem', subgroup: 'smrf' },
    
    // Orthophoto
    'orthophoto-resolution': { group: 'orthophoto', subgroup: 'ortho-opts' },
    'fast-orthophoto': { group: 'orthophoto', subgroup: 'ortho-opts' },
    'orthophoto-cutline': { group: 'orthophoto', subgroup: 'ortho-opts' },
    'skip-orthophoto': { group: 'orthophoto', subgroup: 'ortho-opts' },
    'use-3dmesh': { group: 'orthophoto', subgroup: 'ortho-opts' },
    
    // Tile Exports
    '3d-tiles': { group: 'tiles', subgroup: 'tiles-opts' },
    'tiles': { group: 'tiles', subgroup: 'tiles-opts' },
    
    // System & Pipeline Control
    'max-concurrency': { group: 'system', subgroup: 'performance' },
    'no-gpu': { group: 'system', subgroup: 'performance' },
    'optimize-disk-space': { group: 'system', subgroup: 'performance' },
    'skip-report': { group: 'system', subgroup: 'performance' },
    
    'rerun-from': { group: 'system', subgroup: 'pipeline' },
    'end-with': { group: 'system', subgroup: 'pipeline' }

};

class EditPresetDialog extends React.Component {
    static defaultProps = {
    };

    static propTypes = {
        preset: PropTypes.object.isRequired,
        availableOptions: PropTypes.array.isRequired,
        saveAction: PropTypes.func.isRequired,
        deleteAction: PropTypes.func.isRequired,
        onHide: PropTypes.func,
        pluginContext: PropTypes.object
    };

    constructor(props){
        super(props);

        // Refs to ProcessingNodeOption components
        this.options = {};

        // All collapsed by default
        const collapsedGroups = {};
        OPTS_GROUPS.forEach(g => {
            collapsedGroups[g.id] = true;
        });
        collapsedGroups['ungrouped'] = true;

        this.state = {
            name: props.preset.name,
            search: "",
            showSearch: false,
            collapsedGroups,
            viewMode: 'grouped', // 'grouped' or 'flat',
            expanded: false
        };

        this.getFormData = this.getFormData.bind(this);
        this.onShow = this.onShow.bind(this);
        this.setOptionRef = this.setOptionRef.bind(this);
        this.getOptions = this.getOptions.bind(this);
        this.isCustomPreset = this.isCustomPreset.bind(this);
    }

    setOptionRef(optionName){
        return (component) => {
            if (component) this.options[optionName] = component;
        }
    }

    getOptions(){
        return Object.values(this.options)
          .map(option => {
            return {
              name: option.props.name,
              value: option.getValue()
            };
          })
          .filter(option => option.value !== undefined);
    }

    // What plugins can read and change in this dialog: values set here
    // are as if the user had typed them
    getPluginTaskOptions(availableOptions){
        const setOption = (name, value) => {
            const option = this.options[name];
            if (!option) return false;
            option.setValue(value);
            return true;
        };

        return {
            getOptions: this.getOptions,
            getOption: name => this.options[name] ? this.options[name].getValue() : undefined,
            setOption,
            setOptions: options => options.filter(opt => setOption(opt.name, opt.value)).length > 0,
            resetOption: name => setOption(name, undefined),
            availableOptions
        };
    }

    getFormData(){
      return {
        id: this.props.preset.id,
        name: this.state.name,
        options: this.getOptions()
      };
    }

    isCustomPreset(){
        return this.props.preset.id === -1;
    }

    onShow(){
      if (!this.isCustomPreset()) this.nameInput.focus();
    }

    handleChange(field){
      return (e) => {
        let state = {};
        state[field] = e.target.value;
        this.setState(state);
      }
    }

    toggleSearchControl = () => {
        this.setState({showSearch: !this.state.showSearch});
    }

    toggleGroup = (groupId) => {
        let { collapsedGroups } = this.state;
        collapsedGroups[groupId] = !collapsedGroups[groupId];
        this.setState({ collapsedGroups });
    }

    expandAll = () => {
        const collapsedGroups = {};
        OPTS_GROUPS.forEach(g => collapsedGroups[g.id] = false);
        collapsedGroups['ungrouped'] = false;
        this.setState({ collapsedGroups, expanded: true });
    }

    collapseAll = () => {
        const collapsedGroups = {};
        OPTS_GROUPS.forEach(g => collapsedGroups[g.id] = true);
        collapsedGroups['ungrouped'] = true;
        this.setState({ collapsedGroups, expanded: false });
    }

    toggleViewMode = () => {
        this.setState(prevState => ({
            viewMode: prevState.viewMode === 'grouped' ? 'flat' : 'grouped'
        }));
    }

    componentDidUpdate(prevProps, prevState){
        if (this.state.showSearch && this.searchControl){
            this.searchControl.focus();
        }
    }

    buildOptionsLookup(options) {
        const lookup = {};
        options.forEach(opt => {
            lookup[opt.name] = opt;
        });
        return lookup;
    }

    searchFilter(option) {
        if (!this.state.showSearch || this.state.search === "") return true;
        const searchLower = this.state.search.toLowerCase();
        return option.name.toLowerCase().indexOf(searchLower) !== -1;
    }

    renderOption(option) {
        return (
            <ProcessingNodeOption 
                {...option}
                {...this.optionPluginProps}
                key={option.name}
                ref={this.setOptionRef(option.name)} 
            />
        );
    }

    renderGroupedOptions(options) {
        const lookup = this.buildOptionsLookup(options);
        const assignedOptions = new Set();

        const groupElements = OPTS_GROUPS.map(group => {
            const groupOptions = [];
            
            group.subgroups.forEach(subgroup => {
                const subgroupOptions = Object.keys(OPTION_GROUP_MAP)
                    .filter(optName => {
                        const mapping = OPTION_GROUP_MAP[optName];
                        return mapping.group === group.id && mapping.subgroup === subgroup.id;
                    })
                    .filter(optName => lookup[optName])
                    .filter(optName => this.searchFilter(lookup[optName]))
                    .map(optName => {
                        assignedOptions.add(optName);
                        return lookup[optName];
                    });
                
                if (subgroupOptions.length > 0) {
                    groupOptions.push({
                        subgroup,
                        options: subgroupOptions
                    });
                }
            });

            // Skip empty groups
            if (groupOptions.length === 0) return null;

            const isCollapsed = this.state.collapsedGroups[group.id];
            const totalOptions = groupOptions.reduce((sum, sg) => sum + sg.options.length, 0);

            return (
                <div key={group.id} className="option-group theme-border-highlight-8">
                    <div 
                        className="option-group-header theme-background-highlight" 
                        onClick={() => this.toggleGroup(group.id)}
                    >
                        <i className={`fa ${isCollapsed ? 'fa-chevron-right' : 'fa-chevron-down'} toggle-icon`}></i>
                        <i className={`${group.icon} group-icon`}></i>
                        <span className="group-name">{group.name}</span>
                        <span className="option-count">({totalOptions})</span>
                    </div>
                    
                    <div className="option-group-content" style={{display: isCollapsed ? "none" : "block"}}>
                        {groupOptions.map(({ subgroup, options: subgroupOpts }) => (
                            <div key={subgroup.id} className="option-subgroup">
                                {group.subgroups.length > 1 && (
                                    <div className="option-subgroup-header theme-border-highlight-9">
                                        {subgroup.name}
                                    </div>
                                )}
                                <div className="option-subgroup-content">
                                    {subgroupOpts.map(opt => this.renderOption(opt))}
                                </div>
                            </div>
                        ))}
                    </div>
                </div>
            );
        }).filter(Boolean);

        const ungroupedOptions = options
            .filter(opt => !assignedOptions.has(opt.name))
            .filter(opt => this.searchFilter(opt));

        if (ungroupedOptions.length > 0) {
            const isCollapsed = this.state.collapsedGroups['ungrouped'];
            groupElements.push(
                <div key="ungrouped" className="option-group theme-border-highlight-8">
                    <div 
                        className="option-group-header theme-background-highlight"
                        onClick={() => this.toggleGroup('ungrouped')}
                    >
                        <i className={`fa ${isCollapsed ? 'fa-chevron-right' : 'fa-chevron-down'} toggle-icon`}></i>
                        <i className="fa fa-question-circle group-icon"></i>
                        <span className="group-name">{_('Other Options')}</span>
                        <span className="option-count">({ungroupedOptions.length})</span>
                    </div>
                    
                    {!isCollapsed && (
                        <div className="option-group-content">
                            <div className="option-subgroup-content">
                                {ungroupedOptions.map(opt => this.renderOption(opt))}
                            </div>
                        </div>
                    )}
                </div>
            );
        }

        return groupElements;
    }

    // Render flat view
    renderFlatOptions(options) {
        return options
            .filter(option => this.searchFilter(option))
            .map(option => this.renderOption(option));
    }

    render(){
        let options = PresetUtils.getAvailableOptions(this.props.preset.options, this.props.availableOptions)
                                 .filter(option => OPTS_BLACKLIST.indexOf(option.name.toLowerCase()) === -1);
        
        // Plugins' items and option controls, when a plugin adds some
        const showPanelItems = TaskOptionsPluginItems.hasListeners("addTaskOptionsPanelItem"),
              showOptionControls = TaskOptionsPluginItems.hasListeners("addTaskOptionControl"),
              taskOptions = showPanelItems || showOptionControls ? this.getPluginTaskOptions(options) : null;
        this.optionPluginProps = showOptionControls ? { pluginContext: this.props.pluginContext, taskOptions } : {};

        return (
            <div className="edit-preset-dialog">
                <FormDialog {...this.props}
                    getFormData={this.getFormData} 
                    reset={() => {}}
                    show={true}
                    onShow={this.onShow}
                    saveIcon="far fa-edit"
                    title={_("Edit Task Options")}
                    saveAction={this.props.saveAction}
                    deleteWarning={false}
                    deleteAction={(this.props.preset.id !== -1 && !this.props.preset.system) ? this.props.deleteAction : undefined}>
                  
                  {!this.isCustomPreset() ? 
                    [<div className="preset-name" key="preset">
                        <label className="control-label">{_("Name")}</label>
                        <input type="text" className="form-control" ref={(domNode) => { this.nameInput = domNode; }} value={this.state.name} onChange={this.handleChange('name')} />
                    </div>,
                    <hr key="hr"/>]
                  : ""}

                  {showPanelItems ?
                    <TaskOptionsPluginItems
                        hook="addTaskOptionsPanelItem"
                        className="preset-plugin-items"
                        args={{context: this.props.pluginContext}}
                        itemProps={{context: this.props.pluginContext, taskOptions}} />
                  : ""}

                  <div className="options-toolbar">
                      <button type="button" className="btn btn-default btn-sm" title={_("Search")} onClick={this.toggleSearchControl}>
                          <i className="fa fa-fw fa-search"></i>
                      </button>
                      <button type="button" className="btn btn-default btn-sm" title={this.state.viewMode === 'grouped' ? _("Flat View") : _("Grouped View")} onClick={this.toggleViewMode}>
                          <i className={`fa fa-fw ${this.state.viewMode === 'grouped' ? 'fa-list' : 'fa-layer-group'}`}></i>
                      </button>
                      
                      <button type="button" disabled={this.state.viewMode === 'flat'} className="btn btn-default btn-sm" title={this.state.expanded ? _("Expand") : _("Collapse")} onClick={this.state.expanded ? this.collapseAll : this.expandAll}>
                        <i className={"fa fa-fw fa-angle-double-" + (this.state.expanded ? "up" : "down")}></i>
                      </button>
                  </div>

                  {this.state.showSearch && (
                    <div className="row search-controls">
                        <input 
                            type="text" 
                            className="form-control" 
                            placeholder={_("Search options...")}
                            value={this.state.search} 
                            ref={(node) => { this.searchControl = node; }} 
                            onChange={this.handleChange('search')} 
                        />
                    </div>
                  )}

                  <div className="row options-container">
                    {this.state.viewMode === 'grouped' 
                        ? this.renderGroupedOptions(options)
                        : this.renderFlatOptions(options)
                    }
                  </div>
                </FormDialog>
            </div>
        );
    }
}

export default EditPresetDialog;
