import React from 'react';
import PropTypes from 'prop-types';
import PluginsAPI from '../classes/plugins/API';

// Keeps a plugin's error from breaking the Task Options
class PluginItemBoundary extends React.Component {
    static propTypes = {
        hook: PropTypes.string.isRequired
    };

    constructor(props){
        super(props);
        this.state = { error: false };
    }

    static getDerivedStateFromError(){
        return { error: true };
    }

    componentDidCatch(error){
        console.warn(`A plugin's ${this.props.hook} item failed: ${error}`);
    }

    render(){
        return this.state.error ? null : this.props.children;
    }
}

// Shows what plugins return for one of the Task Options hooks
// (addTaskOptionsFormItem, addTaskOptionsPanelItem, addTaskOptionControl):
// a component, an element or a list of them. Each component is rendered
// with itemProps. Render it only when hasListeners(hook) is true, so that
// the Task Options are unchanged when no plugin uses the hook.
class TaskOptionsPluginItems extends React.Component {
    static defaultProps = {
        args: {},
        itemProps: {},
        className: "",
        inline: false
    };

    static propTypes = {
        hook: PropTypes.string.isRequired,
        args: PropTypes.object,
        itemProps: PropTypes.object,
        className: PropTypes.string,
        inline: PropTypes.bool
    };

    static hasListeners(hook){
        return PluginsAPI.events.listeners(`Dashboard::${hook}`).length > 0;
    }

    constructor(props){
        super(props);
        this.state = { items: [] };
    }

    componentDidMount(){
        const { hook } = this.props;
        const trigger = PluginsAPI.Dashboard["trigger" + hook[0].toUpperCase() + hook.slice(1)];

        try{
            trigger(this.props.args, result => {
                if (this.unmounted) return;

                const items = (Array.isArray(result) ? result : [result])
                    .filter(item => typeof item === "function" || React.isValidElement(item));
                if (items.length > 0) this.setState(state => ({ items: state.items.concat(items) }));
            });
        }catch(e){
            console.warn(`A plugin's ${hook} failed: ${e}`);
        }
    }

    componentWillUnmount(){
        this.unmounted = true;
    }

    render(){
        const { hook, itemProps, className } = this.props;
        if (this.state.items.length === 0) return null;

        const Container = this.props.inline ? "span" : "div";
        return (
            <Container className={"task-options-plugin-items " + className}>
                {this.state.items.map((Item, i) =>
                    <PluginItemBoundary key={i} hook={hook}>
                        {React.isValidElement(Item) ? Item : <Item {...itemProps} />}
                    </PluginItemBoundary>
                )}
            </Container>
        );
    }
}

export default TaskOptionsPluginItems;
