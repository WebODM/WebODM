import React from 'react';
import $ from 'jquery';
import '../css/ProjectList.scss';

import ProjectListItem from './ProjectListItem';
import Paginated from './Paginated';
import Paginator from './Paginator';
import ErrorMessage from './ErrorMessage';
import { _, interpolate } from '../classes/gettext';
import PropTypes from 'prop-types';
import Utils from '../classes/Utils';

class ProjectList extends Paginated {
    static defaultProps = {
        basemaps: []
    }

    static propTypes = {
        history: PropTypes.object.isRequired,
        basemaps: PropTypes.array
    }

    constructor(props){
        super(props);

        this.state = {
            loading: true,
            refreshing: false,
            error: "",
            projects: []
        }

        this.handleDelete = this.handleDelete.bind(this);
    }

    componentDidMount(){
        this.refresh();
    }

    getParametersHash(source){
        if (!source) return "";
        if (source.indexOf("?") === -1) return "";

        let search = source.substr(source.indexOf("?"));
        let q = Utils.queryParams({search});
        
        // All parameters that can change via history.push without
        // triggering a reload of the project list should go here
        delete q.project_task_open;
        delete q.project_task_expanded;

        return JSON.stringify(q);
    }

    componentDidUpdate(prevProps){
        if (this.getParametersHash(prevProps.source) !== this.getParametersHash(this.props.source)){
            this.refresh();
        }
    }

    refresh(){
        this.setState({refreshing: true});

        // Load projects from API
        this.serverRequest = 
            $.getJSON(this.props.source, json => {
                if (json.results){
                    this.setState({
                        projects: json.results,
                        loading: false
                    });
                    this.updatePagination(json.page_size || json.results.length || 1, json.count);
                }else{
                    this.setState({ 
                        error: interpolate(_("Invalid JSON response: %(error)s"), {error: JSON.stringify(json)}),
                        loading: false
                    });
                }
            })
            .fail((jqXHR, textStatus, errorThrown) => {
                this.setState({ 
                    error: interpolate(_("Could not load projects list: %(error)s"), {error: textStatus}),
                    loading: false
                });
            })
            .always(() => {
                this.setState({refreshing: false});
            });
    }

    onPageChanged(pageNum){
        this.refresh();
    }

    componentWillUnmount(){
        this.serverRequest.abort();
    }

    handleDelete(projectId){
        let projects = this.state.projects.filter(p => p.id !== projectId);
        this.setState({projects: projects});
        this.handlePageItemsNumChange(-1, () => {
            this.refresh();
        });
    }

    handleTaskMoved = (task) => {
        if (this["projectListItem_" + task.project]){
            this["projectListItem_" + task.project].newTaskAdded();
        }
    }

    handleProjectDuplicated = () => {
        this.refresh();
    }

    render() {
        if (this.state.loading){
            return (<div className="project-list text-center"><i className="fa fa-circle-notch fa-spin fa-2x fa-fw"></i></div>);
        }else{
            return (<div className="project-list">
                <ErrorMessage bind={[this, 'error']} />
                <Paginator {...this.state.pagination} {...this.props}>
                    <ul key="1" className={"list-group project-list " + (this.state.refreshing ? "refreshing" : "")}>
                        {this.state.projects.map(p => (
                            <ProjectListItem 
                                ref={(domNode) => { this["projectListItem_" + p.id] = domNode }}
                                key={p.id} 
                                data={p} 
                                onDelete={this.handleDelete}
                                onTaskMoved={this.handleTaskMoved}
                                onProjectDuplicated={this.handleProjectDuplicated}
                                history={this.props.history}
                                basemaps={this.props.basemaps} /> 
                        ))}
                    </ul>
                </Paginator>
            </div>);
        }
    }
}

export default ProjectList;
