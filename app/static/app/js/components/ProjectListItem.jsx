import '../css/ProjectListItem.scss';
import React from 'react';
import update from 'immutability-helper';
import TaskList from './TaskList';
import NewTaskPanel from './NewTaskPanel';
import ImportTaskPanel from './ImportTaskPanel';
import ImportExternalPanel from './ImportExternalPanel';
import UploadProgressBar from './UploadProgressBar';
import ErrorMessage from './ErrorMessage';
import EditProjectDialog from './EditProjectDialog';
import SortPanel from './SortPanel';
import Dropzone from '../vendor/dropzone';
import csrf from '../django/csrf';
import HistoryNav from '../classes/HistoryNav';
import Storage from '../classes/Storage';
import PropTypes from 'prop-types';
import ResizeModes from '../classes/ResizeModes';
import Tags from '../classes/Tags';
import exifr from '../vendor/exifr';
import { _, interpolate } from '../classes/gettext';
import $ from 'jquery';

const ACCEPTED_FILES = "image/*,text/plain,.las,.laz,video/*,.srt,.dng,.nef,.gpx";

class ProjectListItem extends React.Component {
  static defaultProps = {
    basemaps: []
  }
  static propTypes = {
      history: PropTypes.object.isRequired,
      data: PropTypes.object.isRequired, // project json
      onDelete: PropTypes.func,
      onTaskMoved: PropTypes.func,
      onProjectDuplicated: PropTypes.func,
      basemaps: PropTypes.array
  }

  constructor(props){
    super(props);

    this.historyNav = new HistoryNav(props.history);

    this.state = {
      showTaskList: this.historyNav.isValueInQSList("project_task_open", props.data.id),
      upload: this.getDefaultUploadState(),
      error: "",
      data: props.data,
      refreshing: false,
      importing: false,
      importingExternal: false,
      buttons: [],
      importItems: [],
      selectImagesItems: [],
      sortKey: Storage.getItem("task_ordering") || "-created_at",
      filterTags: [],
      selectedTags: [],
      filterText: ""
    };

    this.sortItems = [{
        key: "created_at",
        label: _("Created on")
      },{
        key: "name",
        label: _("Name")
      },{
        key: "tags",
        label: _("Tags")
      }];

    this.toggleTaskList = this.toggleTaskList.bind(this);
    this.closeUploadError = this.closeUploadError.bind(this);
    this.cancelUpload = this.cancelUpload.bind(this);
    this.handleCancel = this.handleCancel.bind(this);
    this.handleTaskSaved = this.handleTaskSaved.bind(this);
    this.viewMap = this.viewMap.bind(this);
    this.handleDelete = this.handleDelete.bind(this);
    this.handleEditProject = this.handleEditProject.bind(this);
    this.updateProject = this.updateProject.bind(this);
    this.taskDeleted = this.taskDeleted.bind(this);
    this.taskMoved = this.taskMoved.bind(this);
    this.hasPermission = this.hasPermission.bind(this);
  }

  refresh(){
    // Update project information based on server
    this.setState({refreshing: true});

    this.refreshRequest = 
      $.getJSON(`/api/projects/${this.state.data.id}/`)
        .done((json) => {
          this.setState({data: json});
        })
        .fail((_, __, e) => {
          this.setState({error: e.message});
        })
        .always(() => {
          this.setState({refreshing: false});
        });
  }

  componentWillUnmount(){
    if (this.deleteProjectRequest) this.deleteProjectRequest.abort();
    if (this.refreshRequest) this.refreshRequest.abort();
    if (this.checkQueueCompletedOnTabActivation) document.removeEventListener("visibilitychange", this.checkQueueCompletedOnTabActivation);
  }

  componentDidUpdate(prevProps, prevState){
    if (prevState.filterText !== this.state.filterText ||
        prevState.selectedTags.length !== this.state.selectedTags.length){
      if (this.taskList) this.taskList.applyFilter(this.state.filterText, this.state.selectedTags);
    }
  }

  getDefaultUploadState(){
    return {
      uploading: false,
      editing: false,
      error: "",
      progress: 0,
      files: [],
      totalCount: 0,
      uploadedCount: 0,
      totalBytes: 0,
      totalBytesSent: 0,
      lastUpdated: 0,
      serverTimeouts: 0
    };
  }

  resetUploadState(){
    this.setUploadState(this.getDefaultUploadState());
  }

  setUploadState(props){
    this.setState(update(this.state, {
      upload: {
        $merge: props
      }
    }));
  }

  hasPermission(perm){
    return this.state.data.permissions.indexOf(perm) !== -1;
  }

  componentDidMount(){
    Dropzone.autoDiscover = false;

    if (this.hasPermission("add")){
      const unstableConnection = !!Storage.getItem("unstable_connection");

      this.dz = new Dropzone(this.dropzone, {
          paramName: "images",
          url : 'TO_BE_CHANGED',
          parallelUploads: unstableConnection ? 1 : 6,
          uploadMultiple: false,
          acceptedFiles: ACCEPTED_FILES,
          autoProcessQueue: false,
          createImageThumbnails: false,
          clickable: this.uploadButton,
          maxFilesize: 131072, // 128G
          timeout: 2147483647,
          chunking: true,
          chunkSize: unstableConnection ? 1000000 : 8000000, // 8MB,
          retryChunks: true,
          retryChunksLimit: 20,
          serverTimeoutCallback: () => {
            if (!unstableConnection && this.state.upload.uploading && this.state.upload.progress < 100.0){
              this.setUploadState({serverTimeouts: this.state.upload.serverTimeouts + 1});
            }
          },
          
          headers: {
            [csrf.header]: csrf.token
          }
      });

      const checkQueueCompleted = () => {
        // Prevent double calls to /commit
        if (this.checkTimeout){
          clearTimeout(this.checkTimeout);
          this.checkTimeout = null;
        }
        this.checkTimeout = setTimeout(() => {
          const remainingFilesCount = this.state.upload.totalCount - this.state.upload.uploadedCount;
          if (remainingFilesCount === 0 && this.state.upload.uploadedCount > 0 && this.state.upload.uploading){
            // All files have uploaded!
            const COMMIT_RETRIES = 20;

            const commitUploads = (attempt) => {
              const retryCommit = () => {
                if (attempt < COMMIT_RETRIES){
                  console.warn(`Commit failed, retrying... (${attempt})`);
                  setTimeout(() => {
                    if (this.state.upload.uploading){
                      commitUploads(attempt + 1);
                    }
                  }, 2500 * attempt);
                }else{
                  this.setUploadState({uploading: false, error: _("Cannot create new task. Please try again later.")});
                }
              };

              $.ajax({
                  url: `/api/projects/${this.state.data.id}/tasks/${this.dz._taskInfo.id}/commit/`,
                  contentType: 'application/json',
                  dataType: 'json',
                  type: 'POST',
                  timeout: 15000,
                }).done((task) => {
                  if (task && task.id){
                      this.setUploadState({uploading: false});
                      this.newTaskAdded();
                  }else{
                    retryCommit();
                  }
                }).fail(() => {
                  retryCommit();
                });
            };
            commitUploads(0);
          }else if (this.dz.getQueuedFiles() === 0){
              // Done but didn't upload all?
              this.setUploadState({
                  uploading: false,
                  error: interpolate(_('%(count)s files cannot be uploaded. As a reminder, only images (.jpg, .tif, .png) and GCP files (.txt) can be uploaded. Try again.'), { count: remainingFilesCount })
              });
          }
        }, 250);
      };

      this.dz.on("addedfiles", files => {
          if (this.pluginUpload){
            this.pluginUpload = null;
            this.resetUploadState();
          }

          let totalBytes = 0;

          // Append a suffix to duplicate filenames
          if (this.state.upload.files.length > 0){
            const fileMap = {};
            for (let i = 0; i < this.state.upload.files.length; i++){
              const f = this.state.upload.files[i];
              const filename = f.upload.filename;
              if (!fileMap[filename]) fileMap[filename] = 1;
              else fileMap[filename]++;
            }
            
            for (let i = 0; i < files.length; i++){
              const f = files[i];
              const filename = f.upload.filename;

              if (fileMap[filename] > 0){
                const idx = filename.lastIndexOf(".");
                if (idx !== -1){
                  const name = filename.substring(0, idx);
                  const ext = filename.substring(idx);
                  f.upload.filename = `${name}_${fileMap[filename]}${ext}`;
                  fileMap[filename]++;
                }else{
                  console.warn(`Duplicate ${filename} filename`);
                }
              }
            }
          }

          for (let i = 0; i < files.length; i++){
              totalBytes += files[i].size;
              files[i].deltaBytesSent = 0;
              files[i].trackedBytesSent = 0;
              files[i].retries = 0;
          }

          this.setUploadState({
            editing: true,
            totalCount: this.state.upload.totalCount + files.length,
            files,
            totalBytes: this.state.upload.totalBytes + totalBytes
          });
        })
        .on("uploadprogress", (file, progress, bytesSent) => {
            const now = new Date().getTime();

            if (bytesSent > file.size) bytesSent = file.size;
            
            if (progress === 100 || now - this.state.upload.lastUpdated > 500){
                const deltaBytesSent = bytesSent - file.deltaBytesSent;
                file.trackedBytesSent += deltaBytesSent;

                const totalBytesSent = this.state.upload.totalBytesSent + deltaBytesSent;
                const progress = totalBytesSent / this.state.upload.totalBytes * 100;

                this.setUploadState({
                    progress,
                    totalBytesSent,
                    lastUpdated: now
                });

                file.deltaBytesSent = bytesSent;

                if (this.state.upload.progress === 100){
                  checkQueueCompleted();
                }
            }
        })
        .on("complete", (file) => {
            // Retry
            const retry = () => {
                const MAX_RETRIES = 30;

                if (!file.accepted){
                  throw new Error(interpolate(_('%(filename)s is not a valid file'), {filename: file.name }));
                }

                if (file.retries < MAX_RETRIES){
                    // Update progress
                    const totalBytesSent = this.state.upload.totalBytesSent - file.trackedBytesSent;
                    const progress = totalBytesSent / this.state.upload.totalBytes * 100;
        
                    this.setUploadState({
                        progress,
                        totalBytesSent,
                    });
        
                    file.status = Dropzone.QUEUED;
                    file.deltaBytesSent = 0;
                    file.trackedBytesSent = 0;
                    file.retries++;
                    
                    const retryTime = 2500 * file.retries;

                    // Update serverTimeout so that its at lest 3x retryTime
                    // otherwise a file waiting to be retried could trigger 
                    // a serverTimeout
                    this.dz.options.serverTimeout = Math.max(this.dz.options.serverTimeout, 3 * retryTime);

                    setTimeout(() => {
                      this.dz.processQueue();
                    }, retryTime);
                }else{
                    throw new Error(interpolate(_('Cannot upload %(filename)s, exceeded max retries (%(max_retries)s)'), {filename: file.name, max_retries: MAX_RETRIES}));
                }
            };

            try{
                if (file.status === "error"){
                    if ((file.size / 1024 / 1024) > this.dz.options.maxFilesize) {
                        // Delete from upload queue
                        this.setUploadState({
                            totalCount: this.state.upload.totalCount - 1,
                            totalBytes: this.state.upload.totalBytes - file.size
                        });
                        throw new Error(interpolate(_('Cannot upload %(filename)s, file is too large! Default MaxFileSize is %(maxFileSize)s MB!'), { filename: file.name, maxFileSize: this.dz.options.maxFilesize }));
                    }
                    retry();
                }else{
                    // Check response
                    let response = JSON.parse(file.xhr.response);
                    if (response.success){
                      if (response.uploaded && response.uploaded[file.upload.filename] === file.size){
                        // Update progress by removing the tracked progress and 
                        // use the file size as the true number of bytes
                        let totalBytesSent = this.state.upload.totalBytesSent + file.size;
                        if (file.trackedBytesSent) totalBytesSent -= file.trackedBytesSent;
        
                        const progress = totalBytesSent / this.state.upload.totalBytes * 100;
        
                        this.setUploadState({
                            progress,
                            totalBytesSent,
                            uploadedCount: this.state.upload.uploadedCount + 1,
                            serverTimeouts: 0
                        });

                        checkQueueCompleted();
                      }else{
                        // Chunk success, wait for end
                      }

                      this.dz.processQueue();
                    }else{
                        retry();
                    }
                }
            }catch(e){
                if (this.manuallyCanceled){
                  // Manually canceled, ignore error
                  this.setUploadState({uploading: false});
                }else{
                  this.setUploadState({error: `${e.message}`, uploading: false});
                }

                if (this.dz.files.length) this.dz.cancelUpload();
            }
        })
        .on("reset", () => {
          this.resetUploadState();
        })
        .on("dragenter", () => {
          if (!this.state.upload.editing){
            this.resetUploadState();
          }
        });

      this.checkQueueCompletedOnTabActivation = () => {
        if (document.visibilityState === "visible" && this.state.upload.uploading){
          checkQueueCompleted();
        }
      }
      document.addEventListener("visibilitychange", this.checkQueueCompletedOnTabActivation);
    }
    
    PluginsAPI.Dashboard.triggerAddNewTaskButton({projectId: this.state.data.id, onNewTaskAdded: this.newTaskAdded}, (button) => {
        if (!button) return;

        this.setState(update(this.state, {
            buttons: {$push: [button]}
        }));
    });

    PluginsAPI.Dashboard.triggerAddImportTaskItem({projectId: this.state.data.id, onNewTaskAdded: this.newTaskAdded}, (item) => {
        if (!item) return;

        this.setState(update(this.state, {
            importItems: {$push: [item]}
        }));
    });

    if (this.hasPermission("add")){
      PluginsAPI.Dashboard.triggerAddSelectImagesItem({
        projectId: this.state.data.id,
        acceptedFiles: ACCEPTED_FILES,
        onFilesSelected: this.handlePluginFilesSelected
      }, (item) => {
          if (!item) return;

          this.setState(update(this.state, {
              selectImagesItems: {$push: [item]}
          }));
      });
    }
  }

  handlePluginFilesSelected = (error, files, upload) => {
    if (error){
      this.setUploadState({error});
      return;
    }

    if (this.dz.files.length) this.dz.removeAllFiles(true);

    let totalBytes = 0;
    for (let i = 0; i < files.length; i++) totalBytes += files[i].size || 0;

    this.pluginUpload = upload;
    this.setUploadState(Object.assign(this.getDefaultUploadState(), {
      editing: true,
      files,
      totalCount: files.length,
      totalBytes
    }));
  }

  newTaskAdded = () => {
    this.setState({importing: false, importingExternal: false});
    
    if (this.state.showTaskList){
      this.taskList.refresh();
    }else{
      this.setState({showTaskList: true});
    }
    this.resetUploadState();
    this.refresh();
  }

  setRef(prop){
    return (domNode) => {
      if (domNode != null) this[prop] = domNode;
    }
  }

  toggleTaskList(){
    const showTaskList = !this.state.showTaskList;

    this.historyNav.toggleQSListItem("project_task_open", this.state.data.id, showTaskList);
    
    this.setState({
      showTaskList: showTaskList
    });
  }

  closeUploadError(){
    this.setUploadState({error: ""});
  }

  resetServerTimeouts = () => {
    this.setUploadState({serverTimeouts: 0});
  }

  cancelUpload(){
    this.dz.removeAllFiles(true);
  }

  handleCancel(){
    this.manuallyCanceled = true;
    if (this.pluginUploadReq){
      this.pluginUploadReq.cancel();
      this.pluginUploadReq = null;
      this.pluginUpload = null;
      this.resetUploadState();
    }
    this.cancelUpload();
    if (this.dz._taskInfo && this.dz._taskInfo.id !== undefined){
      $.ajax({
        url: `/api/projects/${this.state.data.id}/tasks/${this.dz._taskInfo.id}/remove/`,
        contentType: 'application/json',
        dataType: 'json',
        type: 'POST'
      });
    }
    setTimeout(() => {
      this.manuallyCanceled = false;
    }, 500);
  }

  taskDeleted(){
    this.refresh();
  }

  taskMoved(task){
    this.refresh();
    if (this.props.onTaskMoved) this.props.onTaskMoved(task);
  }

  handleDelete(){
    return $.ajax({
          url: `/api/projects/${this.state.data.id}/`,
          type: 'DELETE'
        }).done(() => {
          if (this.props.onDelete) this.props.onDelete(this.state.data.id);
        });
  }

  handleTaskSaved(taskInfo){
    this.dz._taskInfo = taskInfo; // Allow us to access the task info from dz

    this.setUploadState({uploading: true, editing: false});

    // Create task
    const formData = {
        name: taskInfo.name,
        options: taskInfo.options,
        processing_node:  taskInfo.selectedNode.id,
        auto_processing_node: taskInfo.selectedNode.key == "auto",
        partial: true,
        align_to: taskInfo.alignTo
    };

    if (taskInfo.resizeMode === ResizeModes.YES){
        formData.resize_to = taskInfo.resizeSize;
    }

    $.ajax({
        url: `/api/projects/${this.state.data.id}/tasks/`,
        contentType: 'application/json',
        data: JSON.stringify(formData),
        dataType: 'json',
        type: 'POST'
      }).done((task) => {
        if (task && task.id){
            this.dz._taskInfo.id = task.id;
            if (this.pluginUpload){
              this.pluginUploadReq = this.pluginUpload({
                project: this.state.data,
                task,
                files: this.state.upload.files
              }, error => {
                this.pluginUploadReq = null;
                this.pluginUpload = null;

                if (error){
                  this.setUploadState({uploading: false, error});
                  $.ajax({
                    url: `/api/projects/${this.state.data.id}/tasks/${task.id}/remove/`,
                    contentType: 'application/json',
                    dataType: 'json',
                    type: 'POST'
                  });
                }else{
                  this.setUploadState({uploading: false});
                  this.newTaskAdded();
                }
              }, (progress, bytesSent, filesSent) => {
                this.setUploadState({
                  progress,
                  totalBytesSent: bytesSent,
                  uploadedCount: filesSent
                });
              });
            }else{
              this.dz.options.url = `/api/projects/${this.state.data.id}/tasks/${task.id}/upload/`;
              this.dz.processQueue();
            }
        }else{
            this.setState({error: interpolate(_('Cannot create new task. Invalid response from server: %(error)s'), { error: JSON.stringify(task) }) });
            this.handleTaskCanceled();
        }
      }).fail(() => {
        this.setState({error: _("Cannot create new task. Please try again later.")});
        this.handleTaskCanceled();
      });
  }

  handleTaskCanceled = () => {
    this.pluginUpload = null;
    this.dz.removeAllFiles(true);
    this.resetUploadState();
  }

  handleUpload = () => {
    // Not a second click for adding more files?
    if (!this.state.upload.editing){
      this.handleTaskCanceled();
    }
  }

  handleEditProject(){
    this.editProjectDialog.show();
  }

  handleHideProject = (deleteWarning, deleteAction) => {
    return () => {
      if (window.confirm(deleteWarning)){
        this.setState({error: "", refreshing: true});
        deleteAction()
          .fail(e => {
            this.setState({error: e.message || (e.responseJSON || {}).detail || e.responseText || _("Could not delete item")});
          }).always(() => {
            this.setState({refreshing: false});
          });
      }
    }
  }

  updateProject(project){
    return $.ajax({
        url: `/api/projects/${this.state.data.id}/edit/`,
        contentType: 'application/json',
        data: JSON.stringify({
          name: project.name,
          description: project.descr,
          tags: project.tags,
          permissions: project.permissions
        }),
        dataType: 'json',
        type: 'POST'
      }).done(() => {
        this.refresh();
      });
  }

  viewMap(){
    location.href = `/map/project/${this.state.data.id}/`;
  }

  handleImportTask = () => {
    this.setState({importing: true, importingExternal: false});
  }

  handleCancelImportTask = () => {
    this.setState({importing: false});
  }

  handleImportExternal = () => {
    this.setState({importingExternal: true, importing: false});
  }

  handleCancelImportExternal = () => {
    this.setState({importingExternal: false});
  }
  

  handleTaskTitleHint = (hasGPSCallback) => {
      return new Promise((resolve, reject) => {
          if (this.state.upload.files.length > 0){

              // Find first image in list
              let f = null;
              for (let i = 0; i < this.state.upload.files.length; i++){
                  if (this.state.upload.files[i].type.indexOf("image") === 0){
                      f = this.state.upload.files[i];
                      break;
                  }
              }
              if (!f){
                  reject();
                  return;
              }
              
              // Parse EXIF
              const options = {
                ifd0: false,
                exif: [0x9003],
                gps: [0x0001, 0x0002, 0x0003, 0x0004],
                interop: false,
                ifd1: false // thumbnail
              };
              const readExif = f => {
                if (f instanceof Blob) return exifr.parse(f, options);
                if (typeof f.parseExif === "function") return f.parseExif(options);
                return Promise.resolve({});
              };

              readExif(f).then(exif => {
                if (!exif || !exif.latitude || !exif.longitude){
                    reject();
                    return;
                }

                if (hasGPSCallback !== undefined) hasGPSCallback();

                let dateTime = exif.DateTimeOriginal;
                if (dateTime && dateTime.toLocaleDateString) dateTime = dateTime.toLocaleDateString();
                
                // Fallback to file modified date if 
                // no exif info is available
                if (!dateTime){
                  if (f.lastModifiedDate) dateTime = f.lastModifiedDate.toLocaleDateString();
                  else if (f.lastModified) dateTime = new Date(f.lastModified).toLocaleDateString();
                }

                // Query nominatim OSM
                $.ajax({
                    url: `https://nominatim.openstreetmap.org/reverse?format=jsonv2&lat=${exif.latitude}&lon=${exif.longitude}`,
                    contentType: 'application/json',
                    type: 'GET'
                }).done(json => {
                    if (json.name) resolve(`${json.name} - ${dateTime}`);
                    else if (json.address && json.address.road) resolve(`${json.address.road} - ${dateTime}`);
                    else reject(new Error("Invalid json"));
                }).fail(reject);
              }).catch(reject);
          }
      });
  }

  sortChanged = key => {
    if (this.taskList){
      this.setState({sortKey: key});
      Storage.setItem("task_ordering", key);
      setTimeout(() => {
        this.taskList.refresh();
      }, 0);
    }
  }

  handleTagClick = tag => {
    return e => {
      const evt = new CustomEvent("onProjectListTagClicked", { detail: tag });
      document.dispatchEvent(evt);
    }
  }

  tagsChanged = (filterTags) => {
    this.setState({filterTags, selectedTags: []});
  }

  handleFilterTextChange = e => {
    this.setState({filterText: e.target.value});
  }

  toggleTag = t => {
    return () => {
      if (this.state.selectedTags.indexOf(t) === -1){
        this.setState(update(this.state, { selectedTags: {$push: [t]} }));
      }else{
        this.setState({selectedTags: this.state.selectedTags.filter(tag => tag !== t)});
      }
    }
  }

  selectTag = t => {
    if (this.state.selectedTags.indexOf(t) === -1){
      this.setState(update(this.state, { selectedTags: {$push: [t]} }));
    }
  }

  clearFilter = () => {
    this.setState({
      filterText: "",
      selectedTags: []
    });
  }

  onOpenFilter = () => {
    if (this.state.filterTags.length === 0){
      setTimeout(() => {
        this.filterTextInput.focus();
      }, 0);
    }
  }

  enableStableMode = () => {
    Storage.setItem("unstable_connection", "1");
    this.handleTaskCanceled();
    location.reload(true);
  }

  render() {
    const { refreshing, data, filterTags } = this.state;
    const numTasks = data.tasks.length;
    const canEdit = this.hasPermission("change");
    const userTags = Tags.userTags(data.tags);
    let deleteWarning = _("All tasks, images and models associated with this project will be permanently deleted. Are you sure you want to continue?");
    if (!data.owned) deleteWarning = _("This project was shared with you. It will not be deleted, but simply hidden from your dashboard. Continue?")
    const ordering = Storage.getItem("task_ordering") || "-created_at";

    return (
      <li className={"project-list-item list-group-item " + (refreshing ? "refreshing" : "")}
         href="javascript:void(0);"
         ref={this.setRef("dropzone")}
         >
        
        {canEdit ? 
            <EditProjectDialog 
            ref={(domNode) => { this.editProjectDialog = domNode; }}
            title={_("Edit Project")}
            saveLabel={_("Save Changes")}
            savingLabel={_("Saving changes...")}
            saveIcon="far fa-edit"
            showDuplicate={true}
            onDuplicated={this.props.onProjectDuplicated}
            projectName={data.name}
            projectDescr={data.description}
            projectId={data.id}
            projectTags={data.tags}
            deleteWarning={deleteWarning}
            saveAction={this.updateProject}
            showPermissions={this.hasPermission("change")}
            deleteAction={this.hasPermission("delete") ? this.handleDelete : undefined}
            />
        : ""}

        <div className="row no-margin">
          <ErrorMessage bind={[this, 'error']} />
          <div className="btn-group project-buttons">
            {this.hasPermission("add") ? 
              <div className={"asset-download-buttons btn-group " + (this.state.upload.uploading ? "hide" : "")}>
                <div className="btn-group">
                  <button type="button" 
                        className="btn btn-primary btn-sm"
                        onClick={this.handleUpload}
                        ref={this.setRef("uploadButton")}>
                    <i className="glyphicon glyphicon-upload"></i>
                    <span className="hidden-xs">{_("Select Images and GCP")}</span>
                  </button>
                  {this.state.selectImagesItems.length ? 
                    [<button key="toggle" type="button" 
                          className="btn btn-primary btn-sm dropdown-toggle"
                          data-toggle="dropdown">
                      <span className="caret"></span>
                    </button>,
                    <ul key="menu" className="dropdown-menu select-images-dropdown">
                      {this.state.selectImagesItems.map((item, i) => <React.Fragment key={i}>{item}</React.Fragment>)}
                    </ul>]
                  : ""}
                </div>
                <button type="button" 
                      className="btn btn-default btn-sm btn-import"
                      data-toggle="dropdown">
                  <i className="glyphicon glyphicon-import"></i> <span className="hidden-xs">{_("Import")}</span> <span className="caret hidden-xs"></span>
                </button>
                <ul className="dropdown-menu import-dropdown">
                  <li><a href="javascript:void(0)" onClick={this.handleImportTask}><i className={"far fa-file-archive fa-fw"}></i> {_("Assets / Backups")}</a></li>
                  <li><a href="javascript:void(0)" onClick={this.handleImportExternal}><i className={"fa fa-cloud-upload-alt fa-fw"}></i> {_("External Data")}</a></li>
                  {this.state.importItems.length ? 
                    this.state.importItems.map((item, i) => <React.Fragment key={i}>{item}</React.Fragment>)
                  : ""}
                </ul>
                {this.state.buttons.map((button, i) => <React.Fragment key={i}>{button}</React.Fragment>)}
              </div>
            : ""}

            <button disabled={this.state.upload.error !== ""} 
                    type="button"
                    className={"btn btn-danger btn-sm " + (!this.state.upload.uploading ? "hide" : "")} 
                    onClick={this.handleCancel}>
              <i className="glyphicon glyphicon-remove-circle"></i>
              Cancel Upload
            </button> 
          </div>

          <div className="project-name">
            {data.name}
            {userTags.length > 0 ? 
              userTags.map((t, i) => <div key={i} className="tag-badge small-badge" onClick={this.handleTagClick(t)}>{t}</div>)
              : ""}
          </div>
          <div className="project-description">
            {data.description}
          </div>
          <div className="row project-links">
            {numTasks > 0 ? 
              <span>
                <i className='fa fa-tasks'></i>
                <a href="javascript:void(0);" onClick={this.toggleTaskList}>
                  {interpolate(_("%(count)s Tasks"), { count: numTasks})} <i className={'fa fa-caret-' + (this.state.showTaskList ? 'down' : 'right')}></i>
                </a>
              </span>
              : ""}
            
            {this.state.showTaskList && numTasks > 1 ? 
              <div className="task-filters">
                <div className="btn-group">
                  {this.state.selectedTags.length || this.state.filterText !== "" ? 
                    <a className="quick-clear-filter" href="javascript:void(0)" onClick={this.clearFilter}>×</a>
                  : ""}
                  <i className='fa fa-filter'></i>
                  <a href="javascript:void(0);" onClick={this.onOpenFilter} className="dropdown-toggle" data-toggle-outside data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                    {_("Filter")}
                  </a>
                  <ul className="dropdown-menu dropdown-menu-right filter-dropdown">
                  <li className="filter-text-container">
                    <input type="text" className="form-control filter-text theme-border-secondary-07" 
                          value={this.state.filterText}
                          ref={domNode => {this.filterTextInput = domNode}}
                          placeholder=""
                          spellCheck="false"
                          autoComplete="false"
                          onChange={this.handleFilterTextChange} />
                  </li>
                  {filterTags.map(t => <li key={t} className="tag-selection">
                    <input type="checkbox"
                        className="filter-checkbox"
                        id={"filter-tag-" + data.id + "-" + t}
                        checked={this.state.selectedTags.indexOf(t) !== -1}
                        onChange={this.toggleTag(t)} /> <label className="filter-checkbox-label" htmlFor={"filter-tag-" + data.id + "-" + t}>{t}</label>
                  </li>)}

                  <li className="clear-container"><input type="button" onClick={this.clearFilter} className="btn btn-default btn-xs" value={_("Clear")}/></li>
                  </ul>
                </div>
                <div className="btn-group">
                  <i className='fa fa-sort-alpha-down'></i>
                  <a href="javascript:void(0);" className="dropdown-toggle" data-toggle="dropdown" aria-haspopup="true" aria-expanded="false">
                    {_("Sort")}
                  </a>
                  <SortPanel selected={ordering} items={this.sortItems} onChange={this.sortChanged} />
                </div>
              </div> : ""}

              {numTasks > 0 ? 
                [<i key="edit-icon" className='fa fa-globe'></i>
                ,<a key="edit-text" href="javascript:void(0);" onClick={this.viewMap}>
                  {_("View Map")}
                </a>]
              : ""}
              
            {canEdit ? 
                [<i key="edit-icon" className='far fa-edit'></i>
                ,<a key="edit-text" href="javascript:void(0);" onClick={this.handleEditProject}> {_("Edit")}
                </a>]
            : ""}

            {!canEdit && !data.owned ? 
              [<i key="edit-icon" className='far fa-eye-slash'></i>
              ,<a key="edit-text" href="javascript:void(0);" onClick={this.handleHideProject(deleteWarning, this.handleDelete)}> {_("Delete")}
              </a>]
            : ""}

          </div>
        </div>
        <i className="drag-drop-icon fa fa-inbox"></i>
        <div className="row">
          {this.state.upload.uploading && this.state.upload.serverTimeouts >= 5 ? 
            <div className="alert alert-warning alert-dismissible">
              <button type="button" className="close" title={_("Close")} onClick={this.resetServerTimeouts}><span aria-hidden="true">&times;</span></button>
              <i className="fa fa-exclamation-triangle"></i> {_("Unstable connection detected. If the upload gets stuck, press the button below to enable stable mode. You will then need to restart the upload.")}
              <button style={{display: "block", marginTop: 16}} type="button" className="btn btn-primary btn-sm" 
                onClick={this.enableStableMode}
              ><i className="fa fa-plug"></i> {_("Enable Stable Mode")}
              </button>
            </div>
          : ""}

          {this.state.upload.uploading ? <UploadProgressBar {...this.state.upload}/> : ""}
          
          {this.state.upload.error !== "" ? 
            <div className="alert alert-warning alert-dismissible">
                <button type="button" className="close" title={_("Close")} onClick={this.closeUploadError}><span aria-hidden="true">&times;</span></button>
                {this.state.upload.error}
            </div>
            : ""}

          {this.state.upload.editing ? 
            <NewTaskPanel
              onSave={this.handleTaskSaved}
              onCancel={this.handleTaskCanceled}
              suggestedTaskName={this.handleTaskTitleHint}
              filesCount={this.state.upload.totalCount}
              showResize={true}
              showAlign={numTasks > 0}
              projectId={this.state.data.id}
              getFiles={() => this.state.upload.files }
              basemaps={this.props.basemaps}
            />
          : ""}

          {this.state.importing ? 
            <ImportTaskPanel
              onImported={this.newTaskAdded}
              onCancel={this.handleCancelImportTask}
              projectId={this.state.data.id}
            />
          : ""}

          {this.state.importingExternal ? 
            <ImportExternalPanel
              onImported={this.newTaskAdded}
              onCancel={this.handleCancelImportExternal}
              projectId={this.state.data.id}
            />
          : ""}

          {this.state.showTaskList ? 
            <TaskList 
                ref={this.setRef("taskList")} 
                source={`/api/projects/${data.id}/tasks/?ordering=${this.state.sortKey}`}
                onDelete={this.taskDeleted}
                onTaskMoved={this.taskMoved}
                hasPermission={this.hasPermission}
                onTagsChanged={this.tagsChanged}
                onTagClicked={this.selectTag}
                history={this.props.history}
            /> : ""}

        </div>
      </li>
    );
  }
}

export default ProjectListItem;
