import React from 'react';
import PropTypes from 'prop-types';
import $ from 'jquery';
import '../../css/modelview/Profile.scss';
import { _ } from '../../classes/gettext';

class ProfilePanel extends React.Component{
  static propTypes = {
    viewer: PropTypes.object.isRequired
  }

  constructor(props){
    super(props);

    this.state = {
      exportOpen: false
    };
  }

  componentDidMount(){
    const { viewer } = this.props;

    document.addEventListener("click", this.closeMenu);

    viewer.profileWindow = new Potree.ProfileWindow(viewer);
    viewer.profileWindowController = new Potree.ProfileWindowController(viewer);

    $(this.root).draggable({handle: $(this.header), containment: "parent"});
    $(this.root).resizable({containment: "parent", handles: "e, s, se", minWidth: 320, minHeight: 220});
  }

  componentWillUnmount(){
    document.removeEventListener("click", this.closeMenu);
  }

  closeMenu = (e) => {
    if (e.target.closest && e.target.closest(".mv-menu-toggle")) return;
    if (this.state.exportOpen) this.setState({exportOpen: false});
  }

  render(){
    const { exportOpen } = this.state;

    return (<div id="profile_window" className="mv-profile"
                 style={{display: "none"}} ref={domNode => { this.root = domNode; }}>
      <div id="profile_titlebar" className="mv-profile-header" ref={domNode => { this.header = domNode; }}>
        <span className="mv-profile-title">{_("Profile")}</span>
        <button type="button" className={"mv-panel-btn mv-menu-toggle " + (exportOpen ? "active" : "")} title={_("Export")}
                onClick={() => this.setState({exportOpen: !exportOpen})}><i className="mv-icon mv-icon-export"></i></button>
        <button type="button" id="closeProfileContainer" className="mv-panel-btn" title={_("Close")}><i className="mv-icon mv-icon-close"></i></button>
      </div>

      {exportOpen ?
      <div className="mv-context-menu mv-export-menu">
        <div onClick={() => document.getElementById("potree_download_csv_icon").click()}>CSV</div>
        <div onClick={() => document.getElementById("potree_download_las_icon").click()}>LAS</div>
      </div> : ""}

      <div id="profile_draw_container" className="mv-profile-body">
        <svg id="profileSVG"></svg>
        <div id="profileCanvasContainer"></div>
        <div id="profileSelectionProperties" style={{display: "none"}}></div>

        <a id="potree_download_profile_ortho_link" href="#" download="profile.csv" style={{display: "none"}}><span id="potree_download_csv_icon"></span></a>
        <a id="potree_download_profile_link" href="#" download="profile.las" style={{display: "none"}}><span id="potree_download_las_icon"></span></a>
      </div>

      <div className="mv-profile-footer">
        <button type="button" id="potree_profile_rotate_cw" title={_("Rotate clockwise")}><i className="mv-icon mv-icon-rotatecw"></i></button>
        <button type="button" id="potree_profile_rotate_ccw" title={_("Rotate counterclockwise")}><i className="mv-icon mv-icon-rotateccw"></i></button>
        <button type="button" id="potree_profile_move_forward" title={_("Move forward")}><i className="mv-icon mv-icon-up"></i></button>
        <button type="button" id="potree_profile_move_backward" title={_("Move backward")}><i className="mv-icon mv-icon-down"></i></button>
      </div>
    </div>);
  }
}

export default ProfilePanel;
