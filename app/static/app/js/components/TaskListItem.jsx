import React from 'react';
import '../css/TaskListItem.scss';
import Console from '../Console';
import statusCodes from '../classes/StatusCodes';
import pendingActions from '../classes/PendingActions';
import ErrorMessage from './ErrorMessage';
import EditTaskPanel from './EditTaskPanel';
import AssetDownloadButtons from './AssetDownloadButtons';
import HistoryNav from '../classes/HistoryNav';
import PropTypes from 'prop-types';
import TaskPluginActionButtons from './TaskPluginActionButtons';
import MoveTaskDialog from './MoveTaskDialog';
import ManageMediaDialog from './ManageMediaDialog';
import SplatsDialog from './SplatsDialog';
import PipelineSteps from '../classes/PipelineSteps';
import Css from '../classes/Css';
import Tags from '../classes/Tags';
import Trans from './Trans';
import Utils from '../classes/Utils';
import PdfPopup from './PdfPopup';
import { unitSystem } from '../classes/Units';
import { _, interpolate } from '../classes/gettext';

class TaskListItem extends React.Component {
  static propTypes = {
      history: PropTypes.object.isRequired,
      data: PropTypes.object.isRequired, // task json
      refreshInterval: PropTypes.number, // how often to refresh info
      onDelete: PropTypes.func,
      onMove: PropTypes.func,
      onDuplicate: PropTypes.func,
      hasPermission: PropTypes.func,
      onEdited: PropTypes.func,
      onTagClicked: PropTypes.func
  }

  constructor(props){
    super();

    this.historyNav = new HistoryNav(props.history);

    this.state = {
      expanded: this.historyNav.isValueInQSList("project_task_expanded", props.data.id),
      task: {},
      time: props.data.processing_time,
      actionError: "",
      actionButtonsDisabled: false,
      editing: false,
      memoryError: false,
      friendlyTaskError: "",
      pluginActionButtons: [],
      view: "basic",
      showMoveDialog: false,
      actionLoading: false,
      thumbLoadFailed: false,
      displayPdf: false,
      copiedToClipboard: false,
      showMediaDialog: false,
      showSplatsDialog: false,
    }

    for (let k in props.data){
      this.state.task[k] = props.data[k];
    }

    this.toggleExpanded = this.toggleExpanded.bind(this);
    this.consoleOutputUrl = this.consoleOutputUrl.bind(this);
    this.stopEditing = this.stopEditing.bind(this);
    this.startEditing = this.startEditing.bind(this);
    this.checkForCommonErrors = this.checkForCommonErrors.bind(this);
    this.handleEditTaskSave = this.handleEditTaskSave.bind(this);
    this.setView = this.setView.bind(this);

    // Retrieve CSS values for status bar colors
    this.backgroundSuccessColor = Css.getValue('theme-background-success', 'backgroundColor');
    this.backgroundFailedColor = Css.getValue('theme-background-failed', 'backgroundColor');
  }

  shouldRefresh(){
    if (this.state.task.pending_action !== null) return true;

    // If a task is completed, or failed, etc. we don't expect it to change
    if ([statusCodes.COMPLETED, statusCodes.FAILED, statusCodes.CANCELED].indexOf(this.state.task.status) !== -1) return false;

    return (([statusCodes.QUEUED, statusCodes.RUNNING, null].indexOf(this.state.task.status) !== -1 && this.state.task.processing_node) ||
            (!this.state.task.uuid && this.state.task.processing_node && !this.state.task.last_error));
  }

  loadTimer(startTime){
    if (!this.processingTimeInterval){
      this._timerStart = new Date().getTime();

      this.setState({time: startTime});

      this.processingTimeInterval = setInterval(() => {
        this.setState({time: ((new Date().getTime() - this._timerStart)) + startTime } );
      }, 1000);
    }
  }

  setView(type){
      return () => {
          this.setState({view: type});
      }
  }

  unloadTimer(){
    if (this.processingTimeInterval){
        clearInterval(this.processingTimeInterval);
        this.processingTimeInterval = null;
    }
    if (this.state.task.processing_time) this.setState({time: this.state.task.processing_time});
  }

  componentDidMount(){
    if (this.shouldRefresh()) this.refreshTimeout = setTimeout(() => this.refresh(), this.props.refreshInterval || 3000);

    // Load timer if we are in running state
    if (this.state.task.status === statusCodes.RUNNING) this.loadTimer(this.state.task.processing_time);
  }

  refresh(){
    // Fetch
    this.refreshRequest = $.getJSON(`/api/projects/${this.state.task.project}/tasks/${this.state.task.id}/`, json => {
      if (json.id){
        let oldStatus = this.state.task.status;

        this.setState({task: json, actionButtonsDisabled: false});

        // Update timer if we switched to running
        if (oldStatus !== this.state.task.status){
          if (this.state.task.status === statusCodes.RUNNING){
            if (this.console) this.console.clear();
            if (this.basicView) this.basicView.reset();
            this.loadTimer(this.state.task.processing_time);
          }else{
            this.setState({time: this.state.task.processing_time});
            this.unloadTimer();
          }

          if (this.state.task.status !== statusCodes.FAILED){
            this.setState({memoryError: false, friendlyTaskError: ""});
          }
        }
      }else{
        console.warn("Cannot refresh task: " + json);
      }

      this.setAutoRefresh();
    })
    .fail((result, __, errorThrown) => {
      if (result.status === 404 || errorThrown === "Not Found"){ // Don't translate this one
        // Assume this has been deleted
        if (this.props.onDelete) this.props.onDelete(this.state.task.id);
      }else{
        this.setAutoRefresh();
      }
    });
  }

  setAutoRefresh(){
    if (this.shouldRefresh()) this.refreshTimeout = setTimeout(() => this.refresh(), this.props.refreshInterval || 3000);
  }

  componentWillUnmount(){
    this.unloadTimer();
    if (this.refreshRequest) this.refreshRequest.abort();
    if (this.refreshTimeout) clearTimeout(this.refreshTimeout);
  }

  toggleExpanded(){
    const expanded = !this.state.expanded;

    this.historyNav.toggleQSListItem("project_task_expanded", this.props.data.id, expanded);

    this.setState({
      expanded: expanded
    });
  }

  consoleOutputUrl(line, download){
    let url = `/api/projects/${this.state.task.project}/tasks/${this.state.task.id}/output/`;
    
    if (download !== undefined){
      url += `?f=raw`;
    }else{
      url += `?f=json`;
    }

    if (line !== undefined){
      url += `&line=${line}&limit=-502`;
    }

    return url;
  }

  thumbnailUrl = () => {
    return `/api/projects/${this.state.task.project}/tasks/${this.state.task.id}/thumbnail?size=164`;  
  }

  hoursMinutesSecs(t){
    if (t === 0 || t === -1) return "-- : -- : --";

    let ch = 60 * 60 * 1000,
          cm = 60 * 1000,
          h = Math.floor(t / ch),
          m = Math.floor( (t - h * ch) / cm),
          s = Math.round( (t - h * ch - m * cm) / 1000),
          pad = function(n){ return n < 10 ? '0' + n : n; };
    if( s === 60 ){
      m++;
      s = 0;
    }
    if( m === 60 ){
      h++;
      m = 0;
    }
    return [pad(h), pad(m), pad(s)].join(':');
  }

  genActionApiCall(action, options = {}){
    return () => {
      const doAction = () => {
        this.setState({actionButtonsDisabled: true});

        let url = `/api/projects/${this.state.task.project}/tasks/${this.state.task.id}/${action}/`;
        $.post(url,
          {
            uuid: this.state.task.uuid
          }
        ).done(json => {
            if (json.success || json.id){
              this.refresh();
              if (options.success !== undefined) options.success(json);
            }else{
              this.setState({
                actionError: json.error || options.defaultError || _("Cannot complete operation."),
                actionButtonsDisabled: false,
                expanded: true
              });
            }
        })
        .fail(() => {
            this.setState({
              actionError: options.defaultError || _("Cannot complete operation."),
              actionButtonsDisabled: false
            });
        })
        .always(() => {
            if (options.always !== undefined) options.always();
        });
      }

      if (options.confirm){
        if (window.confirm(options.confirm)){
          doAction();
        }
      }else{
        doAction();
      }
    };
  }

  optionsToList(options){
    if (!Array.isArray(options)) return "";
    else if (options.length === 0) return _("Default");
    else {
      return options.map(opt => {
        if (opt.name === "boundary") return `${opt.name}:geojson`;
        else return `${opt.name}:${opt.value}`
      }).join(", ");
    }
  }

  startEditing(){
    this.setState({expanded: true, editing: true});
  }

  stopEditing(){
    this.setState({editing: false});
  }

  copyToClipboard = (text) => {
    if (navigator.clipboard !== undefined){
      navigator.clipboard.writeText(text);
    }else{
      // navigator.clipboard is only available in secure contexts (HTTPS)
      const el = document.createElement('textarea');
      el.value = text;
      el.style.position = 'fixed';
      el.style.opacity = '0';
      document.body.appendChild(el);
      el.select();
      try{
        document.execCommand('copy');
      }finally{
        document.body.removeChild(el);
      }
    }
    this.setState({copiedToClipboard: true});
    if (this._clipboardTimeout){
      clearTimeout(this._clipboardTimeout);
      this._clipboardTimeout = null;
    }
    setTimeout(() => {
      this.setState({copiedToClipboard: false});
    }, 2000);
  }

  checkForCommonErrors(lines){
    for (let line of lines){
      if (line.indexOf("Killed") !== -1 ||
          line.indexOf("MemoryError") !== -1 ||
          line.indexOf("std::bad_alloc") !== -1 ||
          line.indexOf("Child returned 137") !== -1 ||
          line.indexOf("loky.process_executor.TerminatedWorkerError:") !== -1 ||
          line.indexOf("Failed to allocate memory") !== -1){
        this.setState({memoryError: true});
      }else if (line.indexOf("SVD did not converge") !== -1 || 
                line.indexOf("0 partial reconstructions in total") !== -1){
        this.setState({friendlyTaskError: interpolate(_("It looks like there might be one of the following problems: %(problems)s You can read more about best practices for capturing good images %(link)s."), { problems: `<ul>
          <li>${_("Not enough images")}</li>
          <li>${_("Not enough overlap between images")}</li>
          <li>${_("Images might be too blurry (common with phone cameras)")}</li>
          <li>${_("The min-num-features task option is set too low, try increasing it by 25%")}</li>
        </ul>`, link: `<a href='https://docs.webodm.net/references/create-successful-maps' target='_blank'>${_("here")}</a>`})});
      }else if (line.indexOf("Illegal instruction") !== -1 ||
                line.indexOf("Child returned 132") !== -1){
        this.setState({friendlyTaskError: interpolate(_("It looks like this computer might be too old. WebODM requires a computer with a 64-bit CPU supporting MMX, SSE, SSE2, SSE3 and SSSE3 instruction set support or higher. You can still run WebODM if you compile your own docker images. See %(link)s for more information."), { link: `<a href='https://docs.webodm.org/installation/#common-troubleshooting'>${_("this page")}</a>` } )});
      }else if (line.indexOf("Child returned 127") !== -1){
        this.setState({friendlyTaskError: _("The processing node is missing a program necessary to complete the task. This might indicate a corrupted installation. If you built ODM, please check that all programs built without errors.")});
      }
    }
  }

  isMacOS(){
    return window.navigator.platform === "MacIntel";
  }

  handleEditTaskSave(task){
    this.setState({task, editing: false});
    if (this.props.onEdited) this.props.onEdited(task);
    this.setAutoRefresh();
  }

  handleMoveTask = () => {
    this.setState({showMoveDialog: true});
  }

  handleDuplicateTask = () => {
    this.setState({actionLoading: true});
    this.genActionApiCall("duplicate", { 
        success: (json) => {
            if (json.task){
                if (this.props.onDuplicate) this.props.onDuplicate(json.task);
            }
        },
        always: () => {
            this.setState({actionLoading: false});
        }})();
  }

  getRestartSubmenuItems(){
    const { task } = this.state;

    // Map rerun-from parameters to display items
    const rfMap = {};
    PipelineSteps.get().forEach(rf => rfMap[rf.action] = rf);

    // Create onClick handlers
    for (let rfParam in rfMap){
      rfMap[rfParam].label = interpolate(_("From %(stage)s"), { stage: rfMap[rfParam].label});
      rfMap[rfParam].onClick = this.genRestartAction(rfParam);
    }

    let items = task.can_rerun_from
            .map(rf => rfMap[rf])
            .filter(rf => rf !== undefined);

    if (items.length > 0 && [statusCodes.CANCELED, statusCodes.FAILED].indexOf(task.status) !== -1){
        // Add resume "pseudo button" to help users understand
        // how to resume a task that failed for memory/disk issues.
        items.unshift({
            label: _("Resume Processing"),
            icon: "fa fa-bolt",
            onClick: this.genRestartAction(task.can_rerun_from[task.can_rerun_from.length - 1])
        });
    }

    return items;
  }

  genRestartAction(rerunFrom = null, options = {}){
    const { task } = this.state;

    const restartAction = this.genActionApiCall("restart", {
        success: () => {
            this.setState({time: -1});
        },
        defaultError: _("Cannot restart task.")
      }
    );

    const setTaskRerunFrom = (value) => {
      this.setState({actionButtonsDisabled: true});

      // Removing rerun-from?
      if (value === null){
        task.options = task.options.filter(opt => opt['name'] !== 'rerun-from');
      }else{
        // Adding rerun-from
        let opt = null;
        if (opt = task.options.find(opt => opt['name'] === 'rerun-from')){
          opt['value'] = value;
        }else{
          // Not in existing list of options, append
          task.options.push({
            name: 'rerun-from',
            value: value
          });
        }
      }

      let data = {
        options: task.options
      };

      // Force reprocess
      if (value === null) data.uuid = '';

      return $.ajax({
          url: `/api/projects/${task.project}/tasks/${task.id}/`,
          contentType: 'application/json',
          data: JSON.stringify(data),
          dataType: 'json',
          type: 'PATCH'
        }).done((taskJson) => {
            this.setState({task: taskJson});
          })
          .fail(() => {
            this.setState({
              actionError: interpolate(_("Cannot restart task from %(stage)s."), { stage: value || _("the start")}),
              actionButtonsDisabled: false
            });
          });
    };

    let doAction = () => {
      setTaskRerunFrom(rerunFrom)
        .then(restartAction);
    };

    return () => {
      if (options.confirm){
        if (window.confirm(options.confirm)){
          doAction();
        }
      }else{
        doAction();
      }
    };
  }

  moveTaskAction = (formData) => {
    if (formData.project !== this.state.task.project){
        return $.ajax({
            url: `/api/projects/${this.state.task.project}/tasks/${this.state.task.id}/`,
            contentType: 'application/json',
            data: JSON.stringify(formData),
            dataType: 'json',
            type: 'PATCH'
          }).done(this.props.onMove);
    }else return false;
  }

  handleTagClick = t => {
    return () => {
      if (this.props.onTagClicked) this.props.onTagClicked(t);
    }
  }

  handleThumbError = e => {
    this.setState({thumbLoadFailed: true});
  }

  spatialRefsToHuman = (refs) => {
    if (refs.indexOf("alignment") !== -1) return _("Alignment");

    let out = [];
    if (refs.indexOf("gps") !== -1){
      out.push(_("GPS"));
    }
    if (refs.indexOf("gcp") !== -1){
      out.push(_("GCP"));
    }

    return out.join("/");
  }

  displayPdf = (url, opts) => {
    if (Utils.isIOS()){
      // PDF viewer in iOS only displays the first page
      // open in a new tab instead
      window.open(url, "pdf_report");
    }else{
      this.setState({displayPdf: {
        url,
        title: opts.title || ""
      }})
    }
  }

  hidePdf = () => {
    this.setState({displayPdf: false});
  }

  render() {
    const task = this.state.task;
    const name = task.name !== null ? task.name : interpolate(_("Task #%(number)s"), { number: task.id });
    const imported = task.import_url !== "";

    let status = statusCodes.description(task.status);
    if (status === "") status = _("Sending images to processing node");

    if (!task.processing_node && !imported && task.status !== statusCodes.COMPLETED) status = _("Waiting for a node...");
    if (task.pending_action !== null) status = pendingActions.description(task.pending_action);

    const disabled = this.state.actionButtonsDisabled || 
                    ([pendingActions.CANCEL,
                      pendingActions.REMOVE,
                      pendingActions.COMPACT,
                      pendingActions.RESTART].indexOf(task.pending_action) !== -1);
    const editable = this.props.hasPermission("change") && [statusCodes.FAILED, statusCodes.COMPLETED, statusCodes.CANCELED].indexOf(task.status) !== -1;
    const actionLoading = this.state.actionLoading;
    const showAssetButtons = task.status === statusCodes.COMPLETED;
    
    let expanded = "";
    if (this.state.expanded){
      let showMemoryErrorWarning = this.state.memoryError && task.status == statusCodes.FAILED && window.location.hostname.indexOf("webodm.net") === -1,
          showTaskWarning = this.state.friendlyTaskError !== "" && task.status == statusCodes.FAILED,
          showExitedWithCodeOneHints = task.last_error === "Process exited with code 1" &&
                                       !showMemoryErrorWarning &&
                                       !showTaskWarning &&
                                       task.status == statusCodes.FAILED,
          memoryErrorLink = this.isMacOS() ? "http://stackoverflow.com/a/39720010" : "https://docs.docker.com/docker-for-windows/#advanced";

      let actionButtons = [];
      const addActionButton = (label, className, icon, onClick, options = {}) => {
        actionButtons.push({
          className, icon, label, onClick, options
        });
      };

      if (showAssetButtons){
        if (task.available_assets.indexOf("orthophoto.tif") !== -1 || task.available_assets.indexOf("dsm.tif") !== -1 || task.available_assets.indexOf("dtm.tif") !== -1){
          addActionButton(" " + _("Map"), "btn-primary", "fa fa-globe fa-fw", () => {
            location.href = `/map/project/${task.project}/task/${task.id}/`;
          });
        }

        if (task.available_assets.indexOf("georeferenced_model.laz") !== -1 || 
            task.available_assets.indexOf("georeferenced_model.las") !== -1 ||
            task.available_assets.indexOf("textured_model.glb") !== -1 ||
            task.available_assets.indexOf("textured_model.zip") !== -1){
          addActionButton(" " + _("3D Model"), "btn-primary", "fa fa-cube fa-fw", () => {
            location.href = `/3d/project/${task.project}/task/${task.id}/`;
          });
        }

        if (task.available_assets.indexOf("report.pdf") !== -1){ 
          addActionButton(" " + _("Report"), "btn-primary", "far fa-file-pdf fa-fw", () => {
            this.displayPdf(`/api/projects/${task.project}/tasks/${task.id}/download/report.pdf?inline=1`, { 
              title: task.name || _("Report")
            });
          }, { className: "btn-margin-right" });
        }
      }

      if (this.props.hasPermission("delete")){
          addActionButton(_("Delete"), "btn-danger", "fa fa-trash fa-fw", this.genActionApiCall("remove", {
            confirm: _("All information related to this task, including images, maps and models will be deleted. Continue?"),
            defaultError: _("Cannot delete task.")
          }), {
            className: "pull-right last-button"
          });
      }

      if ([statusCodes.QUEUED, statusCodes.RUNNING, null].indexOf(task.status) !== -1 &&
         (task.processing_node || imported) && this.props.hasPermission("change")){
        addActionButton(_("Cancel"), "btn-primary", "glyphicon glyphicon-remove-circle", this.genActionApiCall("cancel", {defaultError: _("Cannot cancel task.")}),
          {
            className: "pull-right"
          });
      }

      if ([statusCodes.FAILED, statusCodes.COMPLETED, statusCodes.CANCELED].indexOf(task.status) !== -1 &&
            task.processing_node &&
            this.props.hasPermission("change") &&
            !imported &&
            !task.compacted){
          // By default restart reruns every pipeline
          // step from the beginning
          const rerunFrom = task.can_rerun_from.length > 1 ?
                              task.can_rerun_from[1] :
                              null;

          addActionButton(_("Restart"), "btn-primary", "glyphicon glyphicon-repeat", this.genRestartAction(rerunFrom, {confirm: _("Are you sure you want to restart this task?")}), {
            subItems: this.getRestartSubmenuItems(),
            className: "pull-right"
          });
      }

      if (editable || (!task.processing_node && !imported)){
        addActionButton(_("Edit"), "btn-primary pull-right edit-button", "glyphicon glyphicon-pencil", () => {
          this.startEditing();
        }, {
          className: "inline"
        });
      }

      if (!task.last_error && task.status === null && (task.processing_node || imported) && task.partial && (!task.pending_action || (task.pending_action === pendingActions.RESIZE && !task.resize_progress)) && this.props.hasPermission("change")){
        addActionButton(_("Start Processing"), "btn-primary", "glyphicon glyphicon-saved", this.genActionApiCall("commit", {
            confirm: _("Have all images been uploaded?"),
            defaultError: _("Cannot start processing task.")
          }),
          {
            className: "pull-right"
          });
      }

      actionButtons = (<div className="action-buttons">
            {showAssetButtons ?
              <AssetDownloadButtons task={this.state.task} disabled={disabled} />
            : ""}
            {actionButtons.map(button => {
              const subItems = button.options.subItems || [];
              const className = button.options.className || "";

              let buttonHtml = (<button title={button.label} type="button" className={"btn btn-sm " + button.className} onClick={button.onClick} disabled={disabled}>
                                <i className={button.icon}></i>
                                <span className="hidden-xs hidden-sm">{button.label}</span>
                            </button>);
              if (subItems.length > 0){
                  // The button expands sub items
                  buttonHtml = (<button title={button.label} type="button" className={"btn btn-sm " + button.className} data-toggle="dropdown" disabled={disabled}>
                        <i className={button.icon}></i>
                        <span className="hidden-xs hidden-sm">{button.label}</span>
                    </button>);
              }

              return (
                  <div key={button.label} className={"inline-block " +
                                  (subItems.length > 0 ? "btn-group" : "") + " " +
                                  className}>
                    {buttonHtml}
                    {subItems.length > 0 &&
                      [<button key="dropdown-button"
                              disabled={disabled}
                              type="button"
                              className={"btn btn-sm dropdown-toggle "  + button.className}
                              data-toggle="dropdown"><span className="caret"></span></button>,
                      <ul key="dropdown-menu" className="dropdown-menu">
                        {subItems.map(subItem => <li key={subItem.label}>
                            <a href="javascript:void(0);" onClick={subItem.onClick}><i className={subItem.icon + ' fa-fw '}></i>{subItem.label}</a>
                          </li>)}
                      </ul>]}
                  </div>);
            })}
          </div>);

      const stats = task.statistics;
      const us = unitSystem();

      expanded = (
        <div className="expanded-panel theme-secondary">
          <div className="row">
            <div className="col-md-12 no-padding">
              <div className="col-md-9 col-sm-10 no-padding">
                <table className="table table-condensed info-table">
                  <tbody>
                    <tr>
                      <td><strong>{_("Task ID:")}</strong></td>
                      <td><a title={_("Copy to clipboard")} onClick={() => this.copyToClipboard(task.id)} href="javascript:void(0)" className="task-id-link">{task.id} <i className={"clipboard " + (this.state.copiedToClipboard ? "fa fa-check visible" : "far fa-clipboard")}></i></a></td>
                    </tr>
                    <tr>
                      <td><strong>{_("Created on:")}</strong></td>
                      <td>{(new Date(task.created_at)).toLocaleString()}</td>
                    </tr>
                    {task.status !== statusCodes.COMPLETED && <tr>
                      <td><strong>{_("Processing Node:")}</strong></td>
                      <td>{task.processing_node_name || "-"} ({task.auto_processing_node ? _("auto") : _("manual")})</td>
                    </tr>}
                    {Array.isArray(task.options) &&
                    <tr>
                      <td><strong>{_("Options:")}</strong></td>
                      <td>{this.optionsToList(task.options)}</td>
                    </tr>}
                    {stats && stats.gsd && 
                    <tr>
                      <td><strong>{_("Average GSD:")}</strong></td>
                      <td>{us.length(parseFloat(stats.gsd) / 100, {gsd: true}).toString()}</td>
                    </tr>}
                    {stats && stats.area &&
                    <tr>
                      <td><strong>{_("Area:")}</strong></td>
                       <td>{us.area(parseFloat(stats.area)).toString()}</td>
                    </tr>}
                    {stats && stats.pointcloud && stats.pointcloud.points &&
                    <tr>
                      <td><strong>{_("Points:")}</strong></td>
                      <td>{stats.pointcloud.points.toLocaleString()}</td>
                    </tr>}
                    {stats && stats.spatial_refs && stats.spatial_refs.length ?
                    <tr>
                      <td><strong>{_("Georeferencing:")}</strong></td>
                      <td>{this.spatialRefsToHuman(stats.spatial_refs)}</td>
                    </tr> : null}
                    {task.srs && task.srs.name ?
                    <tr>
                      <td><strong>{_("CRS:")}</strong></td>
                      <td>{task.srs.name}</td>
                    </tr> : null}
                    {task.size > 0 && 
                    <tr>
                      <td><strong>{_("Disk Usage:")}</strong></td>
                      <td>{Utils.bytesToSize(task.size * 1024 * 1024)}</td>
                    </tr>}
                    <tr>
                        <td><strong>{_("Task Output:")}</strong></td>
                        <td><div className="btn-group btn-toggle"> 
                          <button onClick={this.setView("console")} className={"btn btn-xs " + (this.state.view === "basic" ? "btn-default" : "btn-primary")}>{_("On")}</button>
                          <button onClick={this.setView("basic")} className={"btn btn-xs " + (this.state.view === "console" ? "btn-default" : "btn-primary")}>{_("Off")}</button>
                        </div></td>
                    </tr>
                  </tbody>
                </table>
              </div>
              {!this.state.thumbLoadFailed && task.status === statusCodes.COMPLETED ? 
              <div className="col-md-3 col-sm-2 text-center">
                <a href={`/map/project/${task.project}/task/${task.id}/`}>
                  <img onError={this.handleThumbError} className="task-thumbnail" src={this.thumbnailUrl()} alt={_("Thumbnail")}/>
                </a>
              </div> : ""}
              
              {this.state.view === 'console' ?
                <Console
                    className="floatfix"
                    source={this.consoleOutputUrl}
                    refreshInterval={this.shouldRefresh() ? 3000 : undefined}
                    autoscroll={true}
                    height={200}
                    ref={domNode => this.console = domNode}
                    onAddLines={this.checkForCommonErrors}
                    showConsoleButtons={true}
                    maximumLines={500}
                    /> : ""}

              {showMemoryErrorWarning ?
              <div className="task-warning"><i className="fa fa-support"></i> <Trans params={{ memlink: `<a href="${memoryErrorLink}" target='_blank'>${_("enough RAM allocated")}</a>`, cloudlink: `<a href='https://webodm.net' target='_blank'>${_("cloud processing node")}</a>` }}>{_("It looks like your processing node ran out of memory. If you are using docker, make sure that your docker environment has %(memlink)s. Alternatively, make sure you have enough physical RAM, reduce the number of images, make your images smaller, or reduce the max-concurrency parameter from the task's options. You can also try to use a %(cloudlink)s.")}</Trans></div> : ""}

              {showTaskWarning ?
              <div className="task-warning"><i className="fa fa-support"></i> <span dangerouslySetInnerHTML={{__html: this.state.friendlyTaskError}} /></div> : ""}

              {showExitedWithCodeOneHints && window.__taskOptionsDocsLink ?
              <div className="task-warning"><i className="fa fa-info-circle"></i> <div className="inline">
                  <Trans params={{link: `<a href="${window.__taskOptionsDocsLink}" target="_blank">${window.__taskOptionsDocsLink.replace("https://", "")}</a>` }}>{_("\"Process exited with code 1\" means that part of the processing failed. Sometimes it's a problem with the dataset, sometimes it can be solved by tweaking the Task Options. Check the documentation at %(link)s")}</Trans>
                </div>
              </div>
              : ""}
            </div>
          </div>
          <div className="row clearfix">
            {actionButtons}
            {this.state.displayPdf ? 
              <PdfPopup url={this.state.displayPdf.url} 
                        title={this.state.displayPdf.title}
                        onClose={this.hidePdf} /> : ""}
          </div>
          <TaskPluginActionButtons task={task} disabled={disabled} />
        </div>
      );

      // If we're editing, the expanded view becomes the edit panel
      if (this.state.editing){
        expanded = <div className="task-list-item">
          <div className="row no-padding">
            <EditTaskPanel
              task={this.state.task}
              onSave={this.handleEditTaskSave}
              onCancel={this.stopEditing}
            />
          </div>
        </div>;
      }
    }
    
    let statusIcon = statusCodes.icon(task.status);

    // @param type {String} one of: ['neutral', 'done', 'error']
    const getStatusLabel = (text, type = 'neutral', progress = 100) => {
      let color = 'rgba(255, 255, 255, 0.0)';
      if (type === 'done') color = this.backgroundSuccessColor;
      else if (type === 'error') color = this.backgroundFailedColor;
      return (<div 
            className={"status-label theme-border-primary " + type} 
            style={{background: `linear-gradient(90deg, ${color} ${progress}%, rgba(255, 255, 255, 0) ${progress}%)`}}
            title={text}><i className={statusIcon}></i><span> {text}</span></div>);
    }

    let statusLabel = "";
    let showEditLink = false;

    if (task.last_error){
      statusLabel = getStatusLabel(task.last_error, 'error');
    }else if (!task.processing_node && !imported && this.props.hasPermission("change") && task.status !== statusCodes.COMPLETED){
      statusLabel = getStatusLabel(_("Set a processing node"));
      statusIcon = "far fa-hourglass";
      showEditLink = true;
    }else if (task.partial && (!task.pending_action || (task.pending_action === pendingActions.RESIZE && !task.resize_progress))){
      statusIcon = "far fa-hourglass";
      statusLabel = getStatusLabel(_("Waiting to start processing..."));
    }else{
      let progress = 100;
      let type = 'done';

      if (task.pending_action === pendingActions.RESIZE){
          progress = task.resize_progress * 100;
      }else if (task.status === null){
          progress = task.upload_progress * 100;
      }else if (task.status === statusCodes.RUNNING){
          progress = task.running_progress * 100;
      }else if (task.status === statusCodes.FAILED){
          type = 'error';
      }else if (task.status !== statusCodes.COMPLETED){
          type = 'neutral';
      }

      if (task.pending_action === pendingActions.COMPACT){
        statusIcon = 'fa fa-cog fa-spin fa-fw';
      }

      statusLabel = getStatusLabel(status, type, progress);
    }

    const taskActions = [];
    const addTaskAction = (label, icon, onClick) => {
        taskActions.push(
            <li key={label}><a href="javascript:void(0)" onClick={onClick}><i className={icon}></i>{label}</a></li>
        );
    };

    if ([statusCodes.QUEUED, statusCodes.RUNNING, null].indexOf(task.status) !== -1 &&
        (task.processing_node || imported) && this.props.hasPermission("change")){
        addTaskAction(_("Cancel"), "glyphicon glyphicon-remove-circle", this.genActionApiCall("cancel", {defaultError: _("Cannot cancel task.")}));
    }

    // Ability to change options
    if (editable || (!task.processing_node && this.props.hasPermission("change"))){
        taskActions.push(<li key="edit"><a href="javascript:void(0)" onClick={this.startEditing}><i className="glyphicon glyphicon-pencil"></i>{_("Edit")}</a></li>);
    }

    // Media
    if (task.status === statusCodes.COMPLETED){
      taskActions.push(
            <li key="media"><a href="javascript:void(0)" onClick={() => { this.setState({showMediaDialog: true}); }}><i className="fa fa-image"></i>{_("Media")}</a></li>,
            <li key="splats"><a href="javascript:void(0)" onClick={() => { this.setState({showSplatsDialog: true}); }}><i className="fa fa-splat"></i>{_("Splats")}</a></li>,
      );
    }

    if (editable){
        taskActions.push(
            <li key="move"><a href="javascript:void(0)" onClick={this.handleMoveTask}><i className="fa fa-arrows-alt"></i>{_("Move")}</a></li>,
            <li key="duplicate"><a href="javascript:void(0)" onClick={this.handleDuplicateTask}><i className="fa fa-copy"></i>{_("Duplicate")}</a></li>
        );
    }


    if (this.props.hasPermission("delete")){
        taskActions.push(
            <li key="sep" role="separator" className="divider"></li>
        );

        if (task.status === statusCodes.COMPLETED && !task.compacted){
          addTaskAction(_("Compact"), "fa fa-database", this.genActionApiCall("compact", {
              confirm: _("Compacting will free disk space by permanently deleting the original images used for processing. It will no longer be possible to restart the task. Maps and models will remain in place. Continue?"),
              defaultError: _("Cannot compact task.")
          }));
        }
    
        addTaskAction(_("Delete"), "fa fa-trash", this.genActionApiCall("remove", {
            confirm: _("All information related to this task, including images, maps and models will be deleted. Continue?"),
            defaultError: _("Cannot delete task.")
        }));
    }

    let taskActionsIcon = "fa-ellipsis-h";
    if (actionLoading) taskActionsIcon = "fa-circle-notch fa-spin fa-fw";
    const userTags = Tags.userTags(task.tags);

    return (
      <div className="task-list-item">
        {this.state.showMoveDialog ? 
            <MoveTaskDialog 
                task={task}
                ref={(domNode) => { this.moveTaskDialog = domNode; }}
                onHide={() => this.setState({showMoveDialog: false})}
                saveAction={this.moveTaskAction}
            />
        : ""}
        {this.state.showMediaDialog ?
            <ManageMediaDialog
                task={task}
                projectId={task.project}
                canEdit={this.props.hasPermission("change")}
                onClose={() => this.setState({showMediaDialog: false})}
            />
        : ""}
        {this.state.showSplatsDialog ?
            <SplatsDialog
                task={task}
                projectId={task.project}
                canEdit={this.props.hasPermission("change")}
                onClose={() => this.setState({showSplatsDialog: false})}
                onTaskChanged={() => this.refresh()}
            />
        : ""}
        <div className="row">
          <div className="col-xs-7 col-sm-6 col-md-5 col-lg-6 name">
            <i onClick={this.toggleExpanded} className={"clickable far " + (this.state.expanded ? "fa-minus-square" : " fa-plus-square")}></i> <a href="javascript:void(0);" onClick={this.toggleExpanded} className="name-link">{name}</a>
            {userTags.length > 0 ? 
              userTags.map((t, i) => <div key={i} className="tag-badge small-badge" onClick={this.handleTagClick(t)}>{t}</div>)
              : ""}
          </div>
          <div className="col-md-1 hidden-xs hidden-sm details">
            <i className="far fa-image"></i> {task.images_count}
          </div>
          <div className="col-md-2 hidden-xs hidden-sm details">
            <i className="far fa-clock"></i> {this.hoursMinutesSecs(this.state.time)}
          </div>
          <div className="col-xs-5 col-sm-6 col-md-4 col-lg-3 actions">
            {showEditLink ?
              <a href="javascript:void(0);" onClick={this.startEditing}>{statusLabel}</a>
              : statusLabel}
            {taskActions.length > 0 ? 
                <div className="btn-group">
                <button disabled={disabled || actionLoading} className="btn task-actions btn-secondary btn-xs dropdown-toggle" type="button" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                    <i className={"fa " + taskActionsIcon}></i>
                </button>
                <ul className="dropdown-menu dropdown-menu-right">
                    {taskActions}
                </ul>
                </div>
            : ""}
          </div>
        </div>
        <ErrorMessage bind={[this, 'actionError']} />
        {expanded}
      </div>
    );
  }
}

export default TaskListItem;
