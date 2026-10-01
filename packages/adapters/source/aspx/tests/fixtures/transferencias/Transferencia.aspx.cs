using System;
using System.Configuration;
using System.Data.SqlClient;
using System.Web.UI;

// Banco Ficticio S.A.: aplicación de ejemplo, datos inventados.
public partial class Transferencia : Page
{
    protected void Page_Load(object sender, EventArgs e)
    {
        if (!IsPostBack)
        {
            lblMensaje.Text = string.Empty;
        }
    }

    protected void btnTransferir_Click(object sender, EventArgs e)
    {
        string origen = txtCuentaOrigen.Text.Trim();
        string destino = txtCuentaDestino.Text.Trim();
        decimal monto = decimal.Parse(txtMonto.Text);
        string tipo = ddlTipo.SelectedValue;

        if (origen == destino)
        {
            lblMensaje.Text = "LA CUENTA DESTINO ES LA MISMA";
            return;
        }

        string conexion = ConfigurationManager.ConnectionStrings["Banco"].ConnectionString;
        using (SqlConnection cn = new SqlConnection(conexion))
        {
            cn.Open();
            SqlTransaction tx = cn.BeginTransaction();

            SqlCommand leer = new SqlCommand(
                "SELECT CTA_ESTADO, CTA_SALDO FROM CUENTAS WHERE CTA_NUMERO = @cuenta", cn, tx);
            leer.Parameters.AddWithValue("@cuenta", origen);
            SqlDataReader r = leer.ExecuteReader();
            if (!r.Read())
            {
                r.Close();
                tx.Rollback();
                lblMensaje.Text = "CUENTA ORIGEN NO EXISTE";
                return;
            }
            string estado = r.GetString(0);
            decimal saldo = r.GetDecimal(1);
            r.Close();
            if (estado != "A")
            {
                tx.Rollback();
                lblMensaje.Text = "CUENTA ORIGEN INACTIVA";
                return;
            }

            SqlCommand existe = new SqlCommand(
                "SELECT COUNT(*) FROM CUENTAS WHERE CTA_NUMERO = @cuenta AND CTA_ESTADO = 'A'", cn, tx);
            existe.Parameters.AddWithValue("@cuenta", destino);
            if ((int)existe.ExecuteScalar() == 0)
            {
                tx.Rollback();
                lblMensaje.Text = "CUENTA DESTINO NO EXISTE";
                return;
            }

            decimal comision = ComisionService.Calcular(monto, tipo);
            if (saldo < monto + comision)
            {
                tx.Rollback();
                lblMensaje.Text = "SALDO INSUFICIENTE";
                return;
            }

            SqlCommand debitar = new SqlCommand(
                "UPDATE CUENTAS SET CTA_SALDO = CTA_SALDO - @valor WHERE CTA_NUMERO = @cuenta", cn, tx);
            debitar.Parameters.AddWithValue("@valor", monto + comision);
            debitar.Parameters.AddWithValue("@cuenta", origen);
            debitar.ExecuteNonQuery();

            SqlCommand acreditar = new SqlCommand(
                "UPDATE CUENTAS SET CTA_SALDO = CTA_SALDO + @valor WHERE CTA_NUMERO = @cuenta", cn, tx);
            acreditar.Parameters.AddWithValue("@valor", monto);
            acreditar.Parameters.AddWithValue("@cuenta", destino);
            acreditar.ExecuteNonQuery();

            SqlCommand siguiente = new SqlCommand(
                "SELECT ISNULL(MAX(TRF_NUMERO), 0) + 1 FROM TRANSFERENCIAS", cn, tx);
            int numero = (int)siguiente.ExecuteScalar();

            SqlCommand registrar = new SqlCommand(
                "INSERT INTO TRANSFERENCIAS (TRF_NUMERO, TRF_ORIGEN, TRF_DESTINO, TRF_MONTO, TRF_COMISION, TRF_TIPO) " +
                "VALUES (@numero, @origen, @destino, @monto, @comision, @tipo)", cn, tx);
            registrar.Parameters.AddWithValue("@numero", numero);
            registrar.Parameters.AddWithValue("@origen", origen);
            registrar.Parameters.AddWithValue("@destino", destino);
            registrar.Parameters.AddWithValue("@monto", monto);
            registrar.Parameters.AddWithValue("@comision", comision);
            registrar.Parameters.AddWithValue("@tipo", tipo);
            registrar.ExecuteNonQuery();

            tx.Commit();
            lblComision.Text = comision.ToString("0.00");
            lblMensaje.Text = "TRANSFERENCIA REALIZADA";
            Response.Redirect("Comprobante.aspx?numero=" + numero);
        }
    }
}
