import React from 'react';
import '../css/SharePopup.scss';
import PropTypes from 'prop-types';
import ErrorMessage from './ErrorMessage';
import Utils from '../classes/Utils';
import ClipboardInput from './ClipboardInput';
import QRCode from 'qrcode.react';
import update from 'immutability-helper';
import $ from 'jquery';
import PluginsAPI from '../classes/plugins/API';
import { _, interpolate } from '../classes/gettext';
import Storage from '../classes/Storage';

class SharePopup extends React.Component{
  static propTypes = {
    task: PropTypes.object,
    project: PropTypes.object,
    linksTarget: PropTypes.oneOf(['map', '3d']).isRequired,
    placement: PropTypes.string,
    taskChanged: PropTypes.func,
    projectChanged: PropTypes.func,
    queryParams: PropTypes.object,
    showVr: PropTypes.bool
  };
  static defaultProps = {
    task: null,
    project: null,
    showVr: false,
    placement: 'top',
    taskChanged: () => {},
    projectChanged: () => {}
  };

  constructor(props){
    super(props);

    this.state = {
      task: props.task,
      project: props.project,
      togglingShare: false,
      togglingEdits: false,
      error: "",
      showQR: false,
      showVR: false,
      vrLinkCopied: false,
      linkControls: [], // coming from plugins,
      relShareLink: "",
      localLinkAlertDismissed: !!Storage.getItem("local_link_alert_dismissed")
    };

    this.state.relShareLink = this.getRelShareLink();
    this.handleEnableSharing = this.handleEnableSharing.bind(this);
  }

  getRelShareLink = (opts = {}) => {
    let url = "";
    let iframePrefix = opts.iframe ? "iframe/" : "";

    if (this.state.task){
      url = `/public/task/${this.state.task.id}/${iframePrefix}${this.props.linksTarget}/`;
    }else{
      url = `/public/project/${this.state.project.public_id}/${iframePrefix}${this.props.linksTarget}/`;
    }

    if (this.props.queryParams){
      url += Utils.toSearchQuery(this.props.queryParams);
    }
    return url;
  }

  componentWillUnmount(){
    clearTimeout(this.vrLinkTimeout);
  }

  componentDidMount(){
    if ((this.state.task && !this.state.task.public) ||
        (this.state.project && !this.state.project.public)){
      this.handleEnableSharing();
    }

    PluginsAPI.SharePopup.triggerAddLinkControl({
            sharePopup: this
        }, (ctrl) => {
            if (!ctrl) return;

            this.setState(update(this.state, {
                linkControls: {$push: [ctrl]}
            }));
        });
  }

  getApiUrl = () => {
    const { task, project } = this.state;
    return task ? `/api/projects/${task.project}/tasks/${task.id}/` :
                  `/api/projects/${project.id}/`;
  }

  getObjProp = (prop) => {
    const { task, project } = this.state;
    return task ? task[prop] :
                  project[prop];
  }

  handleApiResult = (result) => {
    const { task } = this.state;
    if (task){
      this.setState({task: result});
      this.props.taskChanged(result);
    }else{
      this.setState({project: result});
      this.props.projectChanged(result);
    }
  }

  handleApiFail = () => {
    this.setState({error: _("An error occurred. Check your connection and permissions.")})
  }

  handleEnableSharing(e){
    if (e) e.preventDefault();

    this.setState({togglingShare: true});

    return $.ajax({
        url: this.getApiUrl(),
        contentType: 'application/json',
        data: JSON.stringify({
          public: !this.getObjProp('public')
        }),
        dataType: 'json',
        type: 'PATCH'
      })
      .done(this.handleApiResult)
      .fail(() => this.handleApiFail)
      .always(() => {
        this.setState({togglingShare: false});
      });
  }

  handleAllowEdits = e => {
    e.preventDefault();

    this.setState({togglingEdits: true});

    return $.ajax({
        url: this.getApiUrl(),
        contentType: 'application/json',
        data: JSON.stringify({
          public_edit: !this.getObjProp('public_edit')
        }),
        dataType: 'json',
        type: 'PATCH'
      })
      .done(this.handleApiResult)
      .fail(() => this.handleApiFail)
      .always(() => {
        this.setState({togglingEdits: false});
      });
  }

  toggleQRCode = () => {
    this.setState({showQR: !this.state.showQR, showVR: false});
  }

  toggleVR = () => {
    this.setState({showVR: !this.state.showVR, showQR: false});
  }

  showLocalLinkAlert = () => {
    const link = new URL(Utils.absoluteUrl("/")).hostname;
    return !this.state.localLinkAlertDismissed && 
                      (link.indexOf("0.0.0.0") === 0 || 
                       link.indexOf("localhost") === 0 || 
                       link.indexOf("127.0.0.1") === 0 || 
                       link.indexOf("10.") === 0 || 
                       (link.indexOf("172.") === 0 && parseInt(link.split(".")[1], 10) >= 16 && parseInt(link.split(".")[1], 10) <= 31) || 
                       link.indexOf("192.168.") === 0 || 
                       link.indexOf("::1") === 0);
  }

  hideLocalLinkAlert = () => {
    Storage.setItem("local_link_alert_dismissed", "1");
    this.setState({localLinkAlertDismissed: true});
  }

  render(){
    const shareLink = Utils.absoluteUrl(this.getRelShareLink());
    const vrUrl = new URL(shareLink);
    vrUrl.searchParams.set("autovr", "1");
    const vrLink = vrUrl.toString();
    const iframeUrl = Utils.absoluteUrl(this.getRelShareLink({iframe: true}));
    const iframeCode = `<iframe scrolling="no" title="WebODM" width="61.8033%" height="360" frameBorder="0" src="${iframeUrl}"></iframe>`;
    const isPublic = this.getObjProp('public');
    const projectPopup = !this.state.task && this.state.project;
    const title = this.state.task ? _("Share This Task") : _("Share This Project");

    return (<div onMouseDown={e => { e.stopPropagation(); }} className={"sharePopup " + this.props.placement}>
      <div className={"sharePopupContainer popover in " + this.props.placement + " " + (projectPopup ? "shareProject" : "")}>
        <div className="arrow"></div>
        <h3 className="popover-title theme-background-highlight">{title} 
            <span className="share-toggles">
              {this.props.showVr && window.location.protocol === "https:" ?
              <button type="button" title={_("VR")}
                  className={"btn btn-vr btn-sm " + 
                    (this.state.showVR ? "btn-primary " : "btn-default ") +
                    (!isPublic ? "hide" : "")}
                  onClick={this.toggleVR}>
                    <i className="fa fa-vr-cardboard"></i>
              </button> : ""}
              <button type="button" title={_("QR")}
                  className={"btn btn-qrcode btn-sm " + 
                    (this.state.showQR ? "btn-primary " : "btn-default ") +
                    (!isPublic ? "hide" : "")}
                  onClick={this.toggleQRCode}>
                    <i className="fa fa-qrcode"></i>
              </button>
            </span>
        </h3>
        <div className="popover-content theme-secondary">
          <ErrorMessage bind={[this, 'error']} />
            
          <div className="checkboxes">
            <div className="checkbox">
              <label onClick={this.handleEnableSharing}>
                {this.state.togglingShare ? 
                  <i className="fa fa-sync fa-spin fa-fw"></i>
                : ""}

                <input 
                  className={this.state.togglingShare ? "hide" : ""}
                  type="checkbox" 
                  checked={isPublic}
                  onChange={() => {}}
                  /> {_("Enabled")}
              </label>
            </div>
            {isPublic ? <div className="checkbox last">
              <label onClick={this.handleAllowEdits}>
                {this.state.togglingEdits ? 
                  <i className="fa fa-sync fa-spin fa-fw"></i>
                : ""}

                <input 
                  className={this.state.togglingEdits ? "hide" : ""}
                  type="checkbox" 
                  checked={this.getObjProp('public_edit')}
                  onChange={() => {}}
                  /> {_("Allow Edits")}
              </label>
            </div> : ""}
          </div>
          <div className={"share-links " + (isPublic ? "show" : "")}>
            {this.showLocalLinkAlert() ? 
              <div className="alert alert-warning alert-dismissable link-alert">
                <button type="button" className="close" title={_("Dismiss")} onClick={this.hideLocalLinkAlert}><span aria-hidden="true">&times;</span></button>
                <i className="fa fa-exclamation-triangle"></i>
                <span dangerouslySetInnerHTML={{__html: interpolate(_("The link below is accessible only within your local network. To share a link with others online, use a %(service)s"), {service: `<a href="https://github.com/WebODM/WebODM/blob/master/HOSTED.md" target="_blank">${_("hosted instance")}</a>`})}}></span>
              </div>
            : ""}
            
            <div className={"form-group " + (this.state.showQR || this.state.showVR ? "hide" : "")}>
              <label>
                {_("Link:")}
                <ClipboardInput 
                  type="text" 
                  className="form-control" 
                  value={shareLink} 
                  readOnly={true} 
                  />
              </label>
            </div>
            <div className={"form-group " + (this.state.showQR || this.state.showVR || this.state.linkControls.length === 0 ? "hide" : "")}>
            {this.state.linkControls.map((Ctrl, i) => 
                  <Ctrl key={i} 
                        sharePopup={this}
                      />)}
            </div>
            <div className={"form-group " + (this.state.showQR || this.state.showVR ? "hide" : "")}>
              <label>
                {_("HTML iframe:")}
                <ClipboardInput 
                  type="text" 
                  className="form-control" 
                  value={iframeCode} 
                  readOnly={true} 
                  />
              </label>
            </div>
            <div className={(this.state.showQR ? "" : "hide") + " text-center"}>
              <QRCode
                value={shareLink}
                size={164}
                bgColor={"#ffffff"}
                fgColor={"#000000"}
                level={"M"}
              />
            </div>
            {this.state.showVR ?
            <div>
              <button type="button" className="btn btn-primary btn-block"
                      onClick={() => window.open(`https://www.oculus.com/open_url/?url=${encodeURIComponent(vrLink)}`, "_blank")}>
                <i className="fa fa-vr-cardboard"></i> {_("Open in Meta Quest")}
              </button>
              <button type="button" className="btn btn-default btn-block"
                      onClick={() => {
                        if (navigator.clipboard !== undefined){
                          navigator.clipboard.writeText(vrLink);
                        }else{
                          const el = document.createElement('textarea');
                          el.value = vrLink;
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
                        this.setState({vrLinkCopied: true});
                        clearTimeout(this.vrLinkTimeout);
                        this.vrLinkTimeout = setTimeout(() => this.setState({vrLinkCopied: false}), 2000);
                      }}>
                <i className={"fa fa-fw " + (this.state.vrLinkCopied ? "fa-check" : "fa-clipboard")}></i> {_("Copy VR Link")}
              </button>
            </div> : ""}
          </div>
        </div>
      </div>
    </div>);
  }       
}

export default SharePopup;
