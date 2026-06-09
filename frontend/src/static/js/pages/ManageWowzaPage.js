import React from 'react';
import { ApiUrlContext } from '../utils/contexts/';
import { csrfToken } from '../utils/helpers/';
import { MaterialIcon, SpinnerLoader } from '../components/_shared';
import { MediaListWrapper } from '../components/MediaListWrapper';
import { Page } from './_Page';
import './ManageWowzaPage.scss';

const APP_NAME_RE = /^[A-Za-z0-9_-]{3,80}$/;

function getErrorMessage(error) {
  if (error && error.message) {
    return error.message;
  }
  return 'No fue posible completar la operación.';
}

function getApplicationsSource(status) {
  if (!status) {
    return [];
  }

  if (Array.isArray(status)) {
    return status;
  }

  if (Array.isArray(status.applications)) {
    return status.applications;
  }

  if (status.applications && Array.isArray(status.applications.application)) {
    return status.applications.application;
  }

  if (status.data && Array.isArray(status.data.applications)) {
    return status.data.applications;
  }

  return [];
}

function getAppName(app) {
  if ('string' === typeof app) {
    return app;
  }

  const name = app.name || app.id || app.appName || app.applicationName;

  if (name) {
    return name;
  }

  if (app.href) {
    const parts = app.href.split('/').filter(Boolean);
    return parts[parts.length - 1];
  }

  return '';
}

function normalizeWowzaApplications(status, activeAppName) {
  const applications = getApplicationsSource(status)
    .map((app) => {
      const name = getAppName(app);

      if (!name) {
        return null;
      }

      return {
        name,
        type: 'string' === typeof app ? 'Live' : app.appType || app.type || app.applicationType || 'Live',
        status: 'string' === typeof app ? '' : app.status || app.state || app.applicationStatus || '',
        href: 'string' === typeof app ? '' : app.href || '',
        active: activeAppName === name,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name));

  if (activeAppName && !applications.some((app) => app.name === activeAppName)) {
    applications.unshift({
      name: activeAppName,
      type: 'Live',
      status: 'Creada ahora',
      href: '',
      active: true,
    });
  }

  return applications;
}

export class ManageWowzaPage extends Page {
  constructor(props) {
    super(props, 'manage-wowza');

    this.state = {
      appName: '',
      scheduleId: '',
      isLoadingStatus: true,
      isSubmitting: false,
      status: null,
      result: null,
      activeAppName: '',
      error: null,
      validationError: '',
    };

    this.loadStatus = this.loadStatus.bind(this);
    this.onInputChange = this.onInputChange.bind(this);
    this.onSubmit = this.onSubmit.bind(this);
  }

  componentDidMount() {
    this.loadStatus();
  }

  async loadStatus() {
    this.setState({ isLoadingStatus: true });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaStatus, {
        credentials: 'same-origin',
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza no respondió correctamente.');
      }

      this.setState({
        status: payload.data,
        error: null,
        isLoadingStatus: false,
      });
    } catch (error) {
      this.setState({
        status: null,
        error: getErrorMessage(error),
        isLoadingStatus: false,
      });
    }
  }

  onInputChange(ev) {
    this.setState({
      [ev.currentTarget.name]: ev.currentTarget.value,
      validationError: '',
      result: null,
      error: null,
    });
  }

  async onSubmit(ev) {
    ev.preventDefault();

    const appName = this.state.appName.trim();
    const scheduleId = this.state.scheduleId.trim() || appName;

    if (!APP_NAME_RE.test(appName)) {
      this.setState({
        validationError: 'Usa 3 a 80 caracteres: letras, números, guion o guion bajo.',
      });
      return;
    }

    this.setState({
      isSubmitting: true,
      result: null,
      error: null,
      validationError: '',
    });

    try {
      const response = await fetch(ApiUrlContext._currentValue.manage.wowzaApplications, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken(),
        },
        body: JSON.stringify({
          name: appName,
          schedule_id: scheduleId,
        }),
      });
      const payload = await response.json();

      if (!response.ok || false === payload.success) {
        throw new Error(payload.message || 'Wowza rechazó la solicitud.');
      }

      this.setState({
        appName: '',
        scheduleId: '',
        result: payload,
        activeAppName: appName,
        error: null,
        isSubmitting: false,
      });
      this.loadStatus();
    } catch (error) {
      this.setState({
        error: getErrorMessage(error),
        result: null,
        isSubmitting: false,
      });
    }
  }

  pageContent() {
    const { appName, scheduleId, isLoadingStatus, isSubmitting, status, result, activeAppName, error, validationError } = this.state;
    const previewAppName = appName.trim() || 'nombre_app';
    const previewScheduleId = scheduleId.trim() || previewAppName;
    const applications = normalizeWowzaApplications(status, activeAppName);

    return (
      <MediaListWrapper className="items-list-hor manage-wowza-wrapper">
        <div className="manage-wowza-page">
          <div className="manage-wowza-head">
            <div>
              <h1>Wowza control</h1>
              <p>Crear aplicaciones live y aplicar módulos operativos de Stream Publisher y Push Publish.</p>
            </div>
            <button className="manage-wowza-refresh" onClick={this.loadStatus} disabled={isLoadingStatus}>
              <MaterialIcon type="refresh" />
              <span>Actualizar estado</span>
            </button>
          </div>

          <div className={`manage-wowza-status ${status ? 'manage-wowza-status-available' : 'manage-wowza-status-unavailable'}`}>
            <div className="manage-wowza-status-icon">
              {isLoadingStatus ? <SpinnerLoader size="small" /> : <MaterialIcon type={status ? 'check_circle' : 'error'} />}
            </div>
            <div>
              <strong>{status ? 'Wowza API disponible' : isLoadingStatus ? 'Consultando Wowza' : 'Wowza API no disponible'}</strong>
              <span>
                {status
                  ? 'El panel puede crear aplicaciones en el servidor configurado.'
                  : isLoadingStatus
                  ? 'Validando conectividad con el API Manager.'
                  : 'Revisa conectividad, credenciales o permisos del API Manager.'}
              </span>
            </div>
          </div>

          <section className="manage-wowza-apps">
            <div className="manage-wowza-apps-head">
              <div>
                <h2>Aplicaciones Wowza</h2>
                <span>{applications.length ? `${applications.length} aplicaciones disponibles` : 'Sin aplicaciones reportadas'}</span>
              </div>
              {activeAppName ? <strong>Activa: {activeAppName}</strong> : null}
            </div>

            {isLoadingStatus ? (
              <div className="manage-wowza-apps-empty">
                <SpinnerLoader size="small" />
                <span>Cargando aplicaciones</span>
              </div>
            ) : applications.length ? (
              <div className="manage-wowza-apps-list">
                <div className="manage-wowza-app-row manage-wowza-app-row-head">
                  <span>Aplicación</span>
                  <span>Tipo</span>
                  <span>Estado</span>
                </div>
                {applications.map((app) => (
                  <div className={`manage-wowza-app-row ${app.active ? 'manage-wowza-app-row-active' : ''}`} key={app.name}>
                    <span>
                      <MaterialIcon type={app.active ? 'radio_button_checked' : 'radio_button_unchecked'} />
                      <strong>{app.name}</strong>
                    </span>
                    <span>{app.type}</span>
                    <span>{app.active ? 'Activa' : app.status || 'Disponible'}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="manage-wowza-apps-empty">
                <MaterialIcon type="info" />
                <span>Crea una aplicación para verla en este listado.</span>
              </div>
            )}
          </section>

          <div className="manage-wowza-layout">
            <form className="manage-wowza-form" onSubmit={this.onSubmit}>
              <div className="manage-wowza-form-head">
                <MaterialIcon type="settings_input_antenna" />
                <h2>Nueva aplicación live</h2>
              </div>

              <label>
                Nombre de aplicación
                <input
                  name="appName"
                  value={appName}
                  onChange={this.onInputChange}
                  placeholder="eventoz06"
                  autoComplete="off"
                />
              </label>

              <label>
                ID schedule SMIL
                <input
                  name="scheduleId"
                  value={scheduleId}
                  onChange={this.onInputChange}
                  placeholder={previewAppName}
                  autoComplete="off"
                />
              </label>

              {validationError ? <div className="manage-wowza-message manage-wowza-message-error">{validationError}</div> : null}
              {error ? <div className="manage-wowza-message manage-wowza-message-error">{error}</div> : null}
              {result ? <div className="manage-wowza-message manage-wowza-message-success">Aplicación creada y configurada correctamente.</div> : null}

              <button className="manage-wowza-submit" type="submit" disabled={isSubmitting}>
                {isSubmitting ? <SpinnerLoader size="small" /> : <MaterialIcon type="add_circle" />}
                <span>{isSubmitting ? 'Creando aplicación' : 'Crear aplicación'}</span>
              </button>
            </form>

            <section className="manage-wowza-preview">
              <div className="manage-wowza-preview-head">
                <MaterialIcon type="rule" />
                <h2>Configuración aplicada</h2>
              </div>
              <dl>
                <dt>Tipo</dt>
                <dd>Live</dd>
                <dt>Stream type</dt>
                <dd>live</dd>
                <dt>HLS packetizer</dt>
                <dd>cupertinostreamingpacketizer</dd>
                <dt>HTTP streamer</dt>
                <dd>cupertinostreaming</dd>
                <dt>SMIL schedule</dt>
                <dd>{`streamschedule-${previewScheduleId}.smil`}</dd>
                <dt>Módulos</dt>
                <dd>Core, Logging, FLVPlayback, StreamPublisher, PushPublish</dd>
              </dl>
            </section>
          </div>

          {result ? (
            <section className="manage-wowza-result">
              <h2>Respuesta Wowza</h2>
              <pre>{JSON.stringify(result, null, 2)}</pre>
            </section>
          ) : null}
        </div>
      </MediaListWrapper>
    );
  }
}
