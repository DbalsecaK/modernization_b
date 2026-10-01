<%@ Page Language="C#" AutoEventWireup="true" CodeFile="Comprobante.aspx.cs" Inherits="Comprobante" %>
<%-- Banco Ficticio S.A.: aplicación de ejemplo, datos inventados. --%>
<!DOCTYPE html>
<html xmlns="http://www.w3.org/1999/xhtml">
<head runat="server">
    <title>Comprobante</title>
</head>
<body>
    <form id="form1" runat="server">
        <h1>Comprobante de transferencia</h1>
        <asp:Label ID="lblNumeroTexto" runat="server" AssociatedControlID="lblNumero" Text="Número" />
        <asp:Label ID="lblNumero" runat="server" />
        <asp:Label ID="lblMontoTexto" runat="server" AssociatedControlID="lblMonto" Text="Monto" />
        <asp:Label ID="lblMonto" runat="server" />
        <asp:HyperLink ID="lnkNueva" runat="server" NavigateUrl="~/Transferencia.aspx" Text="Nueva transferencia" />
    </form>
</body>
</html>
